"""A synchronous MCP stdio client, because the pipeline is synchronous.

The `mcp` SDK is async and its session lives inside an anyio task group, so entering and
leaving it from different tasks is not allowed. The wrapper here therefore runs one
coroutine, on one event loop, on one background thread, for the whole life of the client.
That coroutine owns the session and reads requests off a queue. Every public method on
this class blocks the calling thread until that coroutine answers.

The alternative, `asyncio.run` per tool call, relaunches the server subprocess on every
call. Correct, and about fifty times slower over a run.

The server is launched with the interpreter running this process and the four environment
variables from `contracts/mcp_tools.md`. The window is in the launcher's environment, which
means it is in the workflow file, which means widening it is a diff on a pull request.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import pathlib
import sys
import threading
from typing import Any

from mcp import Client, StdioServerParameters

from digest.errors import DigestError, WindowViolation

__all__ = [
    "SERVER_SCRIPTS",
    "server_spec",
    "McpToolClient",
    "repo_root",
]

SERVER_SCRIPTS = {
    "gong": "mcp/gong_server.py",
    "salesforce": "mcp/salesforce_server.py",
}

_START_TIMEOUT_SECONDS = 60.0
_CALL_TIMEOUT_SECONDS = 120.0


def repo_root() -> pathlib.Path:
    """The code repository root, found from this file rather than from the cwd."""
    return pathlib.Path(__file__).resolve().parents[3]


def server_spec(name: str, *, mock_dir: str | pathlib.Path,
                window_from: str, window_to: str, row_cap: int = 200,
                root: str | pathlib.Path | None = None) -> dict[str, Any]:
    """The MCP client server spec for one of the two mock servers."""
    if name not in SERVER_SCRIPTS:
        raise DigestError("unknown mock server %r, expected one of %s"
                          % (name, ", ".join(sorted(SERVER_SCRIPTS))))
    base = pathlib.Path(root) if root is not None else repo_root()
    return {
        "command": sys.executable,
        "args": [str(base / SERVER_SCRIPTS[name])],
        "env": {
            "DIGEST_MOCK_DIR": str(mock_dir),
            "DIGEST_WINDOW_FROM": window_from,
            "DIGEST_WINDOW_TO": window_to,
            "DIGEST_ROW_CAP": str(row_cap),
        },
        "cwd": str(base),
    }


class McpToolClient:
    """One launched stdio MCP server, callable from synchronous code.

    Use it as a context manager. The server is a subprocess and is never left running.
    """

    def __init__(self, name: str, command: str, args: list[str],
                 env: dict[str, str], cwd: str | None = None) -> None:
        self.name = name
        self.env = dict(env)
        merged = dict(os.environ)
        merged.update(self.env)
        self._params = StdioServerParameters(command=command, args=list(args),
                                             env=merged, cwd=cwd)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._queue: asyncio.Queue | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._failure: BaseException | None = None

    # -- construction ------------------------------------------------------
    @classmethod
    def for_server(cls, name: str, *, mock_dir: str | pathlib.Path,
                   window_from: str, window_to: str, row_cap: int = 200,
                   root: str | pathlib.Path | None = None) -> "McpToolClient":
        spec = server_spec(name, mock_dir=mock_dir, window_from=window_from,
                           window_to=window_to, row_cap=row_cap, root=root)
        return cls(name, spec["command"], spec["args"], spec["env"], spec["cwd"])

    @property
    def window(self) -> dict[str, str]:
        """The window this client launched the server with. The connector needs it to
        know where "from the beginning" starts when there is no watermark yet."""
        return {"from": self.env["DIGEST_WINDOW_FROM"], "to": self.env["DIGEST_WINDOW_TO"]}

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "McpToolClient":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name="mcp-%s" % self.name,
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(_START_TIMEOUT_SECONDS):
            raise DigestError("mock %s MCP server did not start within %.0f seconds"
                              % (self.name, _START_TIMEOUT_SECONDS))
        if self._failure is not None:
            raise DigestError("mock %s MCP server failed to start: %s"
                              % (self.name, self._failure))
        return self

    def close(self) -> None:
        if self._thread is None:
            return
        loop, queue = self._loop, self._queue
        if loop is not None and queue is not None and not self._stopped.is_set():
            loop.call_soon_threadsafe(queue.put_nowait, None)
        self._thread.join(timeout=_START_TIMEOUT_SECONDS)
        self._thread = None
        self._loop = None
        self._queue = None

    def __enter__(self) -> "McpToolClient":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- the background coroutine -----------------------------------------
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve(loop))
        except BaseException as exc:  # noqa: BLE001 - surfaced to the calling thread
            self._failure = exc
        finally:
            self._stopped.set()
            self._ready.set()
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    async def _serve(self, loop: asyncio.AbstractEventLoop) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        self._queue = queue
        self._loop = loop
        async with Client(self._params) as client:
            self._ready.set()
            while True:
                item = await queue.get()
                if item is None:
                    return
                method, args, kwargs, future = item
                try:
                    result = await getattr(client, method)(*args, **kwargs)
                    loop.call_soon_threadsafe(_settle, future, result, None)
                except BaseException as exc:  # noqa: BLE001 - handed to the caller
                    loop.call_soon_threadsafe(_settle, future, None, exc)

    def _submit(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._thread is None:
            self.start()
        if self._stopped.is_set():
            raise DigestError("mock %s MCP server is not running" % self.name)
        future: concurrent.futures.Future = concurrent.futures.Future()
        loop, queue = self._loop, self._queue
        assert loop is not None and queue is not None
        loop.call_soon_threadsafe(queue.put_nowait, (method, args, kwargs, future))
        return future.result(timeout=_CALL_TIMEOUT_SECONDS)

    # -- the surface the connectors use ------------------------------------
    def list_tools(self) -> list[dict[str, Any]]:
        result = self._submit("list_tools")
        return [{"name": t.name, "description": t.description or "",
                 "inputSchema": t.input_schema} for t in result.tools]

    def list_tool_names(self) -> list[str]:
        return [t["name"] for t in self.list_tools()]

    def call(self, tool: str, arguments: dict[str, Any] | None = None,
             schema: str | None = None) -> dict[str, Any]:
        """Call one tool and return the parsed JSON document.

        Raises `WindowViolation` when the server refuses the window. Nothing is trimmed
        and nothing is retried: a refusal that turns into a smaller result set looks
        exactly like a quiet day.
        """
        result = self._submit("call_tool", tool, dict(arguments or {}))
        text = "\n".join(block.text for block in result.content
                         if getattr(block, "type", None) == "text")
        if result.is_error:
            self._raise_tool_error(tool, text)
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DigestError("mock %s tool %s returned text that is not JSON: %s"
                              % (self.name, tool, text[:200])) from exc
        if schema is not None:
            # The client validates what the server already validated. Two validations of
            # the same document on purpose: the server proves it wrote a legal response
            # and the connector proves it received one.
            from digest.contracts import validate

            validate(document, schema)
        return document

    def _raise_tool_error(self, tool: str, text: str) -> None:
        if "window_violation:" in text:
            payload = _embedded_json(text)
            requested = payload.get("requested") if payload else None
            allowed = payload.get("allowed") if payload else None
            raise WindowViolation(requested or text, allowed or self.window, tool)
        raise DigestError("mock %s tool %s failed: %s" % (self.name, tool, text or "no detail"))


def _settle(future: concurrent.futures.Future, value: Any,
            error: BaseException | None) -> None:
    if future.set_running_or_notify_cancel():
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(value)


def _embedded_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None
