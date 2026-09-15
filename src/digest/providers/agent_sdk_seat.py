"""The Claude seat adapter: the `claude` CLI, headless, no API key.

This is the default provider. It runs one non interactive turn with tools disabled, hands
the contract schema to the CLI as native structured output, and reads the token counts back
out of the CLI's own JSON result. No session is persisted, so two identical calls cost the
same and neither one leaks into the other.

Two things about the command line are worth stating, because both cost real money when they
are wrong.

First, always pass a system prompt. Without one the call carries the default Claude Code
system prompt, which is tens of thousands of tokens, and every cost number in the write up
becomes a lie.

Second, `--bare` is the documented way to strip the rest of that overhead, and it also skips
keychain reads. On a machine whose seat credentials live in the keychain and which has no
ANTHROPIC_API_KEY set, `--bare` returns "Not logged in" and nothing runs. Verified on this
machine on 2026-09-14. So the default here is `--setting-sources ""`, which strips settings,
memory files and plugin discovery while leaving the keychain alone; measured at about 600
system prompt tokens against about 43,000 without it. Set DIGEST_SEAT_BARE=1, or pass
bare=True, to use `--bare` instead where an API key is present.

Why the CLI rather than the `claude_agent_sdk` package: 0.2.152 does expose structured
output cleanly (ClaudeAgentOptions.output_format takes {"type": "json_schema", "schema": ...}
and the subprocess transport forwards it to the same CLI flag), but its query API is async
and Provider.complete is synchronous. Same process, same flag, one less event loop.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from digest.errors import DigestError
from digest.providers import Capabilities, ProviderResult, TierParams
from digest.providers._families import clamp_effort, family_for

__all__ = ["AgentSdkSeatProvider", "transport_schema", "DEFAULT_TIMEOUT_S"]

DEFAULT_TIMEOUT_S = 300.0

# The CLI validates the schema with a checker that has no copy of the Draft 2020-12 meta
# schema, so a contract schema handed over unchanged is refused with "no schema with key or
# ref". These two keys are the only ones dropped, and both are metadata: the dialect
# declaration and the document's own identifier. Everything that constrains the output,
# additionalProperties: false included, goes over intact, and the router validates the
# answer against the real contract schema afterwards regardless.
_TRANSPORT_STRIPPED = ("$schema", "$id")


def transport_schema(schema: dict) -> dict:
    """The contract schema as the CLI will accept it. Constraints are untouched."""
    return {k: v for k, v in schema.items() if k not in _TRANSPORT_STRIPPED}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class AgentSdkSeatProvider:
    """Calls the `claude` CLI once per completion and parses its JSON result."""

    name = "agent_sdk_seat"

    def __init__(self, *, cli_path: str | None = None, bare: bool | None = None,
                 setting_sources: str = "", timeout: float = DEFAULT_TIMEOUT_S,
                 env: dict[str, str] | None = None, cwd: str | None = None,
                 runner: Any = None) -> None:
        self.cli_path = cli_path or os.environ.get("DIGEST_CLAUDE_CLI") or shutil.which("claude") or "claude"
        self.bare = _env_flag("DIGEST_SEAT_BARE", False) if bare is None else bool(bare)
        self.setting_sources = setting_sources
        self.timeout = float(timeout)
        self.env = env
        self.cwd = cwd
        # Seam for tests: anything with the signature of subprocess.run.
        self._run = runner or subprocess.run

    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_structured=True,     # --json-schema
            strict_tools=False,         # tools are disabled outright on this path
            thinking_style="adaptive",  # the CLI picks the per model interface itself
            effort=True,                # --effort
        )

    def translate_model_id(self, canonical_model_id: str) -> str:
        """The CLI takes the canonical id unchanged."""
        return canonical_model_id

    def build_argv(self, model_id: str, system: str, user: str,
                   schema: dict, params: TierParams) -> tuple[list[str], list[str]]:
        """Build the command line. Returns (argv, dropped_params).

        Kept public because a test that asserts on a command line is worth more than a test
        that asserts on a mock.
        """
        family = family_for(model_id)
        effort, dropped = clamp_effort(params.get("effort"), family)
        argv = [
            self.cli_path,
            "-p", user,
            "--model", model_id,
            "--output-format", "json",
            "--json-schema", json.dumps(transport_schema(schema), sort_keys=True,
                                        separators=(",", ":")),
            "--system-prompt", system,
            "--tools", "",
            "--no-session-persistence",
        ]
        if self.bare:
            argv.append("--bare")
        else:
            argv += ["--setting-sources", self.setting_sources]
        if effort is not None:
            argv += ["--effort", effort]
        if params.get("temperature") is not None:
            # The CLI has no temperature flag; thinking is active on every family it serves.
            dropped.append("temperature")
        return argv, dropped

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult:
        argv, dropped = self.build_argv(model_id, system, user, schema, params)
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=self.timeout,
                             env=self.env, cwd=self.cwd)
        except subprocess.TimeoutExpired as exc:
            raise DigestError("agent_sdk_seat: the claude CLI timed out after %.0fs" % self.timeout) from exc
        except FileNotFoundError as exc:
            raise DigestError("agent_sdk_seat: claude CLI not found at %s" % self.cli_path) from exc
        return self.parse_result(proc.returncode, proc.stdout or "", proc.stderr or "", dropped)

    def parse_result(self, returncode: int, stdout: str, stderr: str,
                     dropped: list[str] | None = None) -> ProviderResult:
        """Turn one CLI JSON result into a ProviderResult, or raise.

        Public so the recorded CLI payloads under tests/fixtures/b5/cli replay through the
        same code that parses a live one.
        """
        dropped = list(dropped or [])
        payload = _parse_json_result(stdout)
        if payload is None:
            raise DigestError(
                "agent_sdk_seat: the claude CLI returned no JSON result (exit %s): %s"
                % (returncode, (stderr or stdout)[:400])
            )
        if returncode != 0 or payload.get("is_error"):
            raise DigestError(
                "agent_sdk_seat: the claude CLI failed (exit %s, terminal_reason %s): %s"
                % (returncode, payload.get("terminal_reason"), str(payload.get("result"))[:400])
            )

        structured = payload.get("structured_output")
        if structured is not None:
            text = json.dumps(structured, ensure_ascii=False)
        else:
            text = payload.get("result") or ""

        usage = payload.get("usage") or {}
        return ProviderResult(
            text=text,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            cache_read=int(usage.get("cache_read_input_tokens") or 0),
            cache_write=int(usage.get("cache_creation_input_tokens") or 0),
            stop_reason=str(payload.get("stop_reason") or "end_turn"),
            dropped_params=dropped,
            provider_reported_cost_usd=_as_float(payload.get("total_cost_usd")),
            path="native_structured",
        )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_json_result(stdout: str) -> dict | None:
    """The CLI prints one JSON document. Fall back to the last JSON line if it prints more."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        doc = json.loads(text)
        return doc if isinstance(doc, dict) else None
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            return doc
    return None
