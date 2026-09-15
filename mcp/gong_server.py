"""Mock Gong MCP server: three read tools over the mock corpus, real response shapes.

Three tools, all read. There is no write tool, not a disabled one and not a gated one,
because the agent cannot ask for what it is not allowed to see if the tool will not form
the query. In production the same three names are backed by the real Gong API and the
change is a base URL plus a credential.

Run it as a script, which is how the MCP client launches it:

    DIGEST_MOCK_DIR=data/mock DIGEST_WINDOW_FROM=2026-09-08 DIGEST_WINDOW_TO=2026-09-08 \
        python mcp/gong_server.py
"""
from __future__ import annotations

from typing import Any

import _mockstore as store
from mcp import types
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools.base import Tool

SERVER_NAME = "gong"

CONFIG, CORPUS = store.boot(SERVER_NAME)

LIST_CALLS_SCHEMA = {
    "type": "object",
    "properties": {
        "from_date_time": {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
        "to_date_time": {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
        "cursor": {
            "type": ["string", "null"],
            "description": "records.cursor from a previous page. Null or omitted for the first page.",
        },
    },
    "required": ["from_date_time", "to_date_time"],
    "additionalProperties": False,
}

CALL_IDS_SCHEMA = {
    "type": "object",
    "properties": {
        "call_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200},
    },
    "required": ["call_ids"],
    "additionalProperties": False,
}


def _call_files(call_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve ids to index entries and call files, silently skipping unknown ids the
    way the real API does. Order follows the request."""
    entries: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for call_id in call_ids:
        entry = CORPUS.entry_for("gong_call", call_id)
        if entry is None:
            continue
        entries.append(entry)
        files.append(CORPUS.file_for(entry, "GongCallFile"))
    return entries, files


def gong_list_calls(from_date_time: str, to_date_time: str,
                    cursor: str | None = None) -> types.CallToolResult:
    refusal = store.check_window("gong_list_calls", from_date_time, to_date_time, CONFIG)
    if refusal is not None:
        return refusal
    start = store.parse_instant(from_date_time)
    end = store.parse_instant(to_date_time, end_of_day=True)
    matched = [e for e in CORPUS.entries("gong_call")
               if start <= store.parse_instant(e["occurred_at"]) <= end]
    offset = store.offset_from_cursor(cursor)
    page = matched[offset:offset + CONFIG.row_cap]
    calls = [store.project(CORPUS.file_for(e, "GongCallFile")["call"]["metaData"],
                           store.GONG_CALL_FIELDS) for e in page]
    next_cursor = store.cursor_for(offset + len(page), len(matched))
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "requestId": store.request_id("gong_list_calls",
                                      {"from": from_date_time, "to": to_date_time,
                                       "cursor": cursor}),
        "records": store.records_block(len(matched), len(calls), next_cursor),
        "calls": calls,
        "meta": store.meta(CONFIG, len(calls), store.GONG_CALL_FIELDS),
    }
    return store.ok(document, "GongCallsResponse")


def gong_get_calls_extensive(call_ids: list[str]) -> types.CallToolResult:
    entries, files = _call_files(call_ids)
    refusal = store.check_record_window("gong_get_calls_extensive", entries, CORPUS)
    if refusal is not None:
        return refusal
    page = files[:CONFIG.row_cap]
    calls = [store.project(f["call"], store.GONG_EXTENSIVE_FIELDS) for f in page]
    next_cursor = store.cursor_for(len(page), len(files))
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "requestId": store.request_id("gong_get_calls_extensive", {"call_ids": call_ids}),
        "records": store.records_block(len(files), len(calls), next_cursor),
        "calls": calls,
        "meta": store.meta(CONFIG, len(calls), store.GONG_EXTENSIVE_FIELDS),
    }
    return store.ok(document, "GongCallsExtensiveResponse")


def gong_get_transcripts(call_ids: list[str]) -> types.CallToolResult:
    entries, files = _call_files(call_ids)
    refusal = store.check_record_window("gong_get_transcripts", entries, CORPUS)
    if refusal is not None:
        return refusal
    page = files[:CONFIG.row_cap]
    transcripts = [store.project(f["transcript"], store.GONG_TRANSCRIPT_FIELDS) for f in page]
    next_cursor = store.cursor_for(len(page), len(files))
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "requestId": store.request_id("gong_get_transcripts", {"call_ids": call_ids}),
        "records": store.records_block(len(files), len(transcripts), next_cursor),
        "callTranscripts": transcripts,
        "meta": store.meta(CONFIG, len(transcripts), store.GONG_TRANSCRIPT_FIELDS),
    }
    return store.ok(document, "GongTranscriptResponse")


def _tool(fn: Any, name: str, description: str, schema: dict[str, Any]) -> Tool:
    tool = Tool.from_function(fn, name=name, description=description)
    # Advertise the contract's own input schema rather than the one derived from the
    # signature, so what a client reads from list_tools is the text in mcp_tools.md.
    tool.parameters = schema
    return tool


TOOLS = [
    _tool(gong_list_calls, "gong_list_calls",
          "List Gong calls whose start time falls in a date range. Mirrors GET /v2/calls.",
          LIST_CALLS_SCHEMA),
    _tool(gong_get_calls_extensive, "gong_get_calls_extensive",
          "Detailed call data including the parties list, which maps speakerId to a person "
          "and their affiliation. Mirrors POST /v2/calls/extensive.",
          CALL_IDS_SCHEMA),
    _tool(gong_get_transcripts, "gong_get_transcripts",
          "Transcripts for the given calls. Mirrors POST /v2/calls/transcript.",
          CALL_IDS_SCHEMA),
]

SERVER = MCPServer(
    SERVER_NAME,
    instructions="Read only mock Gong. Three tools, no write tool, one fixed date window.",
    tools=TOOLS,
)


def main() -> None:
    SERVER.run(transport="stdio")


if __name__ == "__main__":
    main()
