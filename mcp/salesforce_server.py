"""Mock Salesforce MCP server: four read tools over the mock corpus, real response shapes.

Four tools, all read, no write tool. The one that carries the governance point is
`sfdc_get_case`: the SOQL it builds carries `IsPublished = true` in the WHERE clause, so a
private comment is never in the result set. It is not filtered out of the agent's context,
it was never in the query. The count of what was withheld comes back in `meta` so the
withholding lands in the audit log as a number rather than as trust.

Run it as a script, which is how the MCP client launches it:

    DIGEST_MOCK_DIR=data/mock DIGEST_WINDOW_FROM=2026-09-08 DIGEST_WINDOW_TO=2026-09-08 \
        python mcp/salesforce_server.py
"""
from __future__ import annotations

from typing import Any

import _mockstore as store
from mcp import types
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools.base import Tool

SERVER_NAME = "salesforce"

CONFIG, CORPUS = store.boot(SERVER_NAME)

QUERY_CASES_SCHEMA = {
    "type": "object",
    "properties": {
        "created_from": {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
        "created_to": {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
    },
    "required": ["created_from", "created_to"],
    "additionalProperties": False,
}

GET_CASE_SCHEMA = {
    "type": "object",
    "properties": {"case_id": {"type": "string"}},
    "required": ["case_id"],
    "additionalProperties": False,
}


def _ids_schema(key: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            key: {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200},
        },
        "required": [key],
        "additionalProperties": False,
    }


def _in_clause(ids: list[str]) -> str:
    return ", ".join("'%s'" % i for i in ids)


# ---------------------------------------------------------------------------
# Users. salesforce/users.json unioned with traps/users.json when that file exists,
# so the trap author can add an author without touching the generated file.
# ---------------------------------------------------------------------------
_USERS: dict[str, dict[str, Any]] | None = None


def _users() -> dict[str, dict[str, Any]]:
    global _USERS
    if _USERS is None:
        merged: dict[str, dict[str, Any]] = {}
        for relative in ("salesforce/users.json", "traps/users.json"):
            path = CORPUS.config.mock_dir / relative
            if not path.is_file():
                continue
            doc = CORPUS.read_json(relative)
            errors = store.iter_errors(doc, "SalesforceQueryResponse")
            if errors:
                raise store.MockCorpusError(
                    "%s is not a valid SalesforceQueryResponse: %s" % (relative, "; ".join(errors))
                )
            for record in doc["records"]:
                if record.get("attributes", {}).get("type") == "User":
                    merged[record["Id"]] = record
        _USERS = merged
    return _USERS


def sfdc_query_cases(created_from: str, created_to: str) -> types.CallToolResult:
    refusal = store.check_window("sfdc_query_cases", created_from, created_to, CONFIG)
    if refusal is not None:
        return refusal
    start = store.parse_instant(created_from)
    end = store.parse_instant(created_to, end_of_day=True)
    matched = [e for e in CORPUS.entries("sfdc_case")
               if start <= store.parse_instant(e["occurred_at"]) <= end]
    page = matched[:CONFIG.row_cap]
    records = [store.project(CORPUS.file_for(e, "SalesforceCaseFile")["case"],
                             store.SFDC_CASE_FIELDS, keep_attributes=True) for e in page]
    soql = (
        "SELECT %s FROM Case WHERE CreatedDate >= %s AND CreatedDate <= %s "
        "ORDER BY CreatedDate ASC LIMIT %d"
        % (", ".join(store.SFDC_CASE_FIELDS), created_from, created_to, CONFIG.row_cap)
    )
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "totalSize": len(records),
        "done": len(page) == len(matched),
        "records": records,
        "meta": store.meta(CONFIG, len(records), store.SFDC_CASE_FIELDS,
                           withheld_comment_count=0, soql=soql),
    }
    return store.ok(document, "SalesforceQueryResponse")


def sfdc_get_case(case_id: str) -> types.CallToolResult:
    entry = CORPUS.entry_for("sfdc_case", case_id)
    if entry is None:
        raise store.ToolError("not_found: no case with Id %s" % case_id)
    refusal = store.check_record_window("sfdc_get_case", [entry], CORPUS)
    if refusal is not None:
        return refusal
    case_file = CORPUS.file_for(entry, "SalesforceCaseFile")
    all_comments = case_file["comments"]
    # Rule 3. The private rows are read only to be counted; their bodies never enter
    # any structure that is serialised into the response.
    published = [c for c in all_comments if c.get("IsPublished") is True]
    withheld = len(all_comments) - len(published)
    published.sort(key=lambda c: (c["CreatedDate"], c["Id"]))
    page = published[:CONFIG.row_cap]
    comments = [store.project(c, store.SFDC_COMMENT_FIELDS, keep_attributes=True) for c in page]
    soql = (
        "SELECT %s FROM CaseComment WHERE ParentId = '%s' AND IsPublished = true "
        "ORDER BY CreatedDate ASC LIMIT %d"
        % (", ".join(store.SFDC_COMMENT_FIELDS), case_id, CONFIG.row_cap)
    )
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "case": store.project(case_file["case"], store.SFDC_CASE_FIELDS, keep_attributes=True),
        "comments": comments,
        "meta": store.meta(CONFIG, len(comments), store.SFDC_COMMENT_FIELDS,
                           withheld_comment_count=withheld, soql=soql),
    }
    return store.ok(document, "SalesforceCaseResponse")


def sfdc_get_accounts(account_ids: list[str]) -> types.CallToolResult:
    wanted = list(account_ids)
    by_id = {a["record"]["Id"]: a["record"] for a in CORPUS.accounts()["accounts"]}
    found = [by_id[i] for i in wanted if i in by_id]
    page = found[:CONFIG.row_cap]
    records = [store.project(r, store.SFDC_ACCOUNT_FIELDS, keep_attributes=True) for r in page]
    soql = (
        "SELECT %s FROM Account WHERE Id IN (%s) LIMIT %d"
        % (", ".join(store.SFDC_ACCOUNT_FIELDS), _in_clause(wanted), CONFIG.row_cap)
    )
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "totalSize": len(records),
        "done": len(page) == len(found),
        "records": records,
        "meta": store.meta(CONFIG, len(records), store.SFDC_ACCOUNT_FIELDS,
                           withheld_comment_count=0, soql=soql),
    }
    return store.ok(document, "SalesforceQueryResponse")


def sfdc_get_users(user_ids: list[str]) -> types.CallToolResult:
    wanted = list(user_ids)
    directory = _users()
    found = [directory[i] for i in wanted if i in directory]
    page = found[:CONFIG.row_cap]
    records = [store.project(r, store.SFDC_USER_FIELDS, keep_attributes=True) for r in page]
    soql = (
        "SELECT %s FROM User WHERE Id IN (%s) LIMIT %d"
        % (", ".join(store.SFDC_USER_FIELDS), _in_clause(wanted), CONFIG.row_cap)
    )
    document = {
        "schema_version": store.SCHEMA_VERSION,
        "totalSize": len(records),
        "done": len(page) == len(found),
        "records": records,
        "meta": store.meta(CONFIG, len(records), store.SFDC_USER_FIELDS,
                           withheld_comment_count=0, soql=soql),
    }
    return store.ok(document, "SalesforceQueryResponse")


def _tool(fn: Any, name: str, description: str, schema: dict[str, Any]) -> Tool:
    tool = Tool.from_function(fn, name=name, description=description)
    # Advertise the contract's own input schema rather than the one derived from the
    # signature, so what a client reads from list_tools is the text in mcp_tools.md.
    tool.parameters = schema
    return tool


TOOLS = [
    _tool(sfdc_query_cases, "sfdc_query_cases",
          "Cases created in a date range. Mirrors GET /services/data/v62.0/query with a "
          "SOQL SELECT over Case.",
          QUERY_CASES_SCHEMA),
    _tool(sfdc_get_case, "sfdc_get_case",
          "One case with its PUBLISHED comments. Private comments are excluded by the "
          "SOQL, not filtered afterwards.",
          GET_CASE_SCHEMA),
    _tool(sfdc_get_accounts, "sfdc_get_accounts",
          "Account records including the org specific tier, ARR and renewal date custom "
          "fields.",
          _ids_schema("account_ids")),
    _tool(sfdc_get_users, "sfdc_get_users",
          "User records for comment authors, so a connector can tell staff from a portal "
          "user.",
          _ids_schema("user_ids")),
]

SERVER = MCPServer(
    SERVER_NAME,
    instructions="Read only mock Salesforce. Four tools, no write tool, one fixed date window.",
    tools=TOOLS,
)


def main() -> None:
    SERVER.run(transport="stdio")


if __name__ == "__main__":
    main()
