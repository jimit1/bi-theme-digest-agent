"""Shared plumbing for the two mock MCP servers.

Everything both servers need and nothing either of them alone needs: the environment
they boot from, the mock corpus index, the date window check, the field allowlists and
the response envelope. Kept in one file so the two servers cannot drift apart on the
five enforcement rules, which are the whole point of putting a tool boundary here.

This module is imported by `gong_server.py` and `salesforce_server.py`, which sit next
to it. Both are run as scripts, so this directory is already `sys.path[0]`.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any, Iterable

from mcp import types
from mcp.server.mcpserver.exceptions import ToolError

# ---------------------------------------------------------------------------
# sys.path: this directory is called `mcp`, the same name as the installed SDK.
# If the repository root ever lands on sys.path ahead of site-packages, `import mcp`
# would resolve to this directory instead of the SDK. Drop the repository root and
# add `src` explicitly, so the servers can import digest.contracts and nothing else
# shifts underneath them.
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
_SRC = _REPO / "src"


def _fix_sys_path() -> None:
    keep = []
    for entry in sys.path:
        if not entry:
            keep.append(entry)
            continue
        try:
            resolved = pathlib.Path(entry).resolve()
        except OSError:
            keep.append(entry)
            continue
        if resolved == _REPO:
            continue
        keep.append(entry)
    sys.path[:] = keep
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))


_fix_sys_path()

from digest.contracts import iter_errors  # noqa: E402  (after the sys.path fix)

SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Field allowlists, one per object, exactly as contracts/mcp_tools.md states.
# Rule 4 is proved by asserting a returned record's key set equals one of these
# (plus `attributes` for a Salesforce record, which the REST API always returns).
# ---------------------------------------------------------------------------
GONG_CALL_FIELDS = [
    "id", "url", "title", "scheduled", "started", "duration", "primaryUserId",
    "direction", "system", "scope", "media", "language", "workspaceId",
    "sdrDisposition", "clientUniqueId", "customData", "purpose", "meetingUrl",
    "isPrivate", "calendarEventId",
]
GONG_EXTENSIVE_FIELDS = ["metaData", "parties"]
GONG_TRANSCRIPT_FIELDS = ["callId", "transcript"]

SFDC_CASE_FIELDS = [
    "Id", "CaseNumber", "AccountId", "Subject", "Status", "Priority",
    "CreatedDate", "ClosedDate",
]
SFDC_COMMENT_FIELDS = [
    "Id", "ParentId", "CommentBody", "IsPublished", "CreatedById", "CreatedDate",
]
SFDC_ACCOUNT_FIELDS = [
    "Id", "Name", "Tier__c", "ARR__c", "Renewal_Date__c", "Products__c",
]
SFDC_USER_FIELDS = ["Id", "Name", "UserType", "IsActive"]

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MockCorpusError(RuntimeError):
    """The corpus on disk is missing or malformed. A boot failure, not a tool failure."""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def parse_instant(raw: str, *, end_of_day: bool = False) -> _dt.datetime:
    """Parse an ISO 8601 instant, or a bare date, into an aware UTC datetime.

    A bare date is accepted because the window environment variables are written by
    hand in a workflow file and a human writes 2026-09-08, not 2026-09-08T00:00:00Z.
    A bare date as a window start means the first moment of that day and as a window
    end means the last, so both ends stay inclusive.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    if _DATE_ONLY.match(text):
        text = text + ("T23:59:59Z" if end_of_day else "T00:00:00Z")
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("not an ISO 8601 timestamp: %s" % raw) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def format_instant(value: _dt.datetime) -> str:
    """Canonical UTC form, which is what every timestamp pattern in the pack expects."""
    return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ServerConfig:
    """The four environment variables both servers boot from.

    A missing window is a hard boot failure. Defaulting a scoping control to
    "everything" is how the control quietly stops existing, so there is no default.
    """

    def __init__(self, mock_dir: pathlib.Path, window_from: _dt.datetime,
                 window_to: _dt.datetime, row_cap: int) -> None:
        self.mock_dir = mock_dir
        self.window_from = window_from
        self.window_to = window_to
        self.row_cap = row_cap

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ServerConfig":
        env = dict(os.environ if env is None else env)
        raw_from = env.get("DIGEST_WINDOW_FROM", "").strip()
        raw_to = env.get("DIGEST_WINDOW_TO", "").strip()
        missing = [n for n, v in (("DIGEST_WINDOW_FROM", raw_from),
                                  ("DIGEST_WINDOW_TO", raw_to)) if not v]
        if missing:
            raise MockCorpusError(
                "missing required environment variable(s): %s. The date window is a "
                "security boundary and has no default." % ", ".join(missing)
            )
        window_from = parse_instant(raw_from, end_of_day=False)
        window_to = parse_instant(raw_to, end_of_day=True)
        if window_to < window_from:
            raise MockCorpusError(
                "DIGEST_WINDOW_TO (%s) is before DIGEST_WINDOW_FROM (%s)" % (raw_to, raw_from)
            )
        raw_cap = env.get("DIGEST_ROW_CAP", "").strip() or "200"
        try:
            row_cap = int(raw_cap)
        except ValueError as exc:
            raise MockCorpusError("DIGEST_ROW_CAP is not an integer: %s" % raw_cap) from exc
        if row_cap < 1:
            raise MockCorpusError("DIGEST_ROW_CAP must be at least 1, got %d" % row_cap)
        mock_dir = pathlib.Path(env.get("DIGEST_MOCK_DIR", "").strip() or "data/mock")
        if not mock_dir.is_absolute():
            mock_dir = (pathlib.Path.cwd() / mock_dir).resolve()
        return cls(mock_dir, window_from, window_to, row_cap)

    @property
    def window(self) -> dict[str, str]:
        return {"from": format_instant(self.window_from), "to": format_instant(self.window_to)}


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------

class MockCorpus:
    """index.json plus the files it names, loaded lazily and cached.

    Trap files come through this same code path. A trap that loads differently from a
    generated fixture tests the loader instead of the pipeline.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._index: dict[str, Any] | None = None
        self._files: dict[str, dict[str, Any]] = {}
        self._accounts: dict[str, Any] | None = None

    # -- raw reads ---------------------------------------------------------
    def read_json(self, relative: str) -> dict[str, Any]:
        path = (self.config.mock_dir / relative).resolve()
        root = self.config.mock_dir.resolve()
        if root not in path.parents and path != root:
            raise MockCorpusError("path escapes the mock directory: %s" % relative)
        if not path.is_file():
            raise MockCorpusError("mock file not found: %s" % path)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def index(self) -> dict[str, Any]:
        if self._index is None:
            doc = self.read_json("index.json")
            errors = iter_errors(doc, "MockIndex")
            if errors:
                raise MockCorpusError("index.json is not a valid MockIndex: %s" % "; ".join(errors))
            self._index = doc
        return self._index

    def entries(self, kind: str) -> list[dict[str, Any]]:
        rows = [e for e in self.index()["entries"] if e["kind"] == kind]
        rows.sort(key=lambda e: (e["occurred_at"], e["id"]))
        return rows

    def entry_for(self, kind: str, record_id: str) -> dict[str, Any] | None:
        for entry in self.entries(kind):
            if entry["id"] == record_id:
                return entry
        return None

    def file_for(self, entry: dict[str, Any], schema_name: str) -> dict[str, Any]:
        path = entry["path"]
        cached = self._files.get(path)
        if cached is None:
            cached = self.read_json(path)
            errors = iter_errors(cached, schema_name)
            if errors:
                raise MockCorpusError(
                    "%s is not a valid %s: %s" % (path, schema_name, "; ".join(errors))
                )
            self._files[path] = cached
        return cached

    def accounts(self) -> dict[str, Any]:
        if self._accounts is None:
            doc = self.read_json("accounts.json")
            errors = iter_errors(doc, "MockAccountsFile")
            if errors:
                raise MockCorpusError(
                    "accounts.json is not a valid MockAccountsFile: %s" % "; ".join(errors)
                )
            self._accounts = doc
        return self._accounts

    # -- window ------------------------------------------------------------
    def in_window(self, entry: dict[str, Any]) -> bool:
        occurred = parse_instant(entry["occurred_at"])
        return self.config.window_from <= occurred <= self.config.window_to


# ---------------------------------------------------------------------------
# Rule 2: the window violation
# ---------------------------------------------------------------------------

def window_violation(tool: str, requested_from: str, requested_to: str,
                     config: ServerConfig) -> types.CallToolResult:
    """Build the refusal. Nothing is trimmed, because a trimmed result looks like a
    quiet day and the worst outcome for a digest agent is a digest that looks normal
    and is missing a day."""
    allowed = config.window
    payload = {
        "code": "window_violation",
        "message": "requested window is outside the window this server is configured for",
        "requested": {"from": requested_from, "to": requested_to},
        "allowed": allowed,
        "tool": tool,
    }
    text = (
        "window_violation: requested window from %s to %s is outside the window this "
        "server is configured for, which is from %s to %s (tool %s). %s"
        % (requested_from, requested_to, allowed["from"], allowed["to"], tool,
           json.dumps(payload, sort_keys=True))
    )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], isError=True
    )


def check_window(tool: str, requested_from: str, requested_to: str,
                 config: ServerConfig) -> types.CallToolResult | None:
    """Return a refusal when the request reaches outside the configured window."""
    try:
        start = parse_instant(requested_from)
        end = parse_instant(requested_to, end_of_day=True)
    except ValueError as exc:
        raise ToolError("bad_request: %s" % exc) from exc
    if start < config.window_from or end > config.window_to:
        return window_violation(tool, requested_from, requested_to, config)
    return None


def check_record_window(tool: str, entries: Iterable[dict[str, Any]],
                        corpus: MockCorpus) -> types.CallToolResult | None:
    """An id based tool is scoped too: asking for a record outside the window is the
    same request as asking for the day it happened on, so it is refused the same way."""
    outside = [e for e in entries if not corpus.in_window(e)]
    if not outside:
        return None
    first = min(outside, key=lambda e: e["occurred_at"])
    last = max(outside, key=lambda e: e["occurred_at"])
    return window_violation(tool, first["occurred_at"], last["occurred_at"], corpus.config)


# ---------------------------------------------------------------------------
# Projection and envelope
# ---------------------------------------------------------------------------

def project(record: dict[str, Any], allowlist: list[str], *,
            keep_attributes: bool = False) -> dict[str, Any]:
    """Rule 4. Nothing returns a field the pipeline did not ask for."""
    out: dict[str, Any] = {}
    if keep_attributes and "attributes" in record:
        out["attributes"] = record["attributes"]
    for field in allowlist:
        if field not in record:
            raise MockCorpusError("record is missing allowlisted field %r" % field)
        out[field] = record[field]
    return out


def meta(config: ServerConfig, rows_returned: int, fields_allowlisted: list[str], *,
         withheld_comment_count: int | None = None, soql: str | None = None) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "window": config.window,
        "rows_returned": rows_returned,
        "row_cap": config.row_cap,
        "withheld_comment_count": withheld_comment_count,
        "fields_allowlisted": list(fields_allowlisted),
    }
    if soql is not None:
        envelope["soql"] = soql
    return envelope


def records_block(total: int, page_size: int, cursor: str | None) -> dict[str, Any]:
    return {
        "totalRecords": total,
        "currentPageSize": page_size,
        "currentPageNumber": 0,
        "cursor": cursor,
    }


def request_id(tool: str, arguments: dict[str, Any]) -> str:
    """Deterministic, so a recorded run replays byte for byte."""
    blob = tool + "|" + json.dumps(arguments, sort_keys=True, default=str)
    return "req-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:6]


def cursor_for(offset: int, total: int) -> str | None:
    """Rule 5. A cap that silently drops rows is indistinguishable from a quiet day,
    so a capped page always carries the cursor that says there is more."""
    return "offset:%d" % offset if offset < total else None


def offset_from_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    match = re.fullmatch(r"offset:(\d+)", cursor)
    if not match:
        raise ToolError("bad_request: unrecognised cursor %r" % cursor)
    return int(match.group(1))


# ---------------------------------------------------------------------------
# Returning
# ---------------------------------------------------------------------------

def ok(document: dict[str, Any], schema_name: str) -> types.CallToolResult:
    """Validate before returning. The server proves it wrote a legal response and the
    connector proves it received one: two validations of the same document on purpose."""
    errors = iter_errors(document, schema_name)
    if errors:
        raise ToolError(
            "server_contract_violation: response failed %s validation: %s"
            % (schema_name, "; ".join(errors))
        )
    text = json.dumps(document, ensure_ascii=False, sort_keys=False)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                isError=False)


def boot(server_name: str) -> tuple[ServerConfig, MockCorpus]:
    """Read the environment or exit non zero naming the variable that is missing."""
    try:
        config = ServerConfig.from_env()
    except MockCorpusError as exc:
        sys.stderr.write("%s: %s\n" % (server_name, exc))
        raise SystemExit(2)
    return config, MockCorpus(config)
