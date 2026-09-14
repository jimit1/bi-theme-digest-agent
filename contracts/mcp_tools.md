# MCP tool signatures for the two mock servers

Two local MCP servers serve the mock corpus over the MCP protocol. The pipeline never opens
a mock file directly; it calls a tool. In production the same tool names are backed by the
real APIs and the change is a base URL plus a credential, because the mock serves the real
response shapes.

JSON in, JSON out. Every response validates against a schema in this pack before the
connector returns it, and the connector validates it again on receipt. Two validations of
the same document is deliberate: the server proves it wrote a legal response and the client
proves it received one.

## The rule that makes this least privilege

**There is no write tool.** Not a disabled one, not a gated one. The agent cannot ask for
what it is not allowed to see, because the tool will not form the query.

## Gong server: `mcp/gong_server.py`

### `gong_list_calls`

```json
{
  "name": "gong_list_calls",
  "description": "List Gong calls whose start time falls in a date range. Mirrors GET /v2/calls.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "from_date_time": {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
      "to_date_time":   {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
      "cursor":         {"type": ["string", "null"], "description": "records.cursor from a previous page. Null or omitted for the first page."}
    },
    "required": ["from_date_time", "to_date_time"],
    "additionalProperties": false
  }
}
```

Returns `GongCallsResponse`.

### `gong_get_calls_extensive`

```json
{
  "name": "gong_get_calls_extensive",
  "description": "Detailed call data including the parties list, which maps speakerId to a person and their affiliation. Mirrors POST /v2/calls/extensive.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "call_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200}
    },
    "required": ["call_ids"],
    "additionalProperties": false
  }
}
```

Returns `GongCallsExtensiveResponse`. Only `metaData` and `parties` come back, because the
field allowlist asks for nothing else.

### `gong_get_transcripts`

```json
{
  "name": "gong_get_transcripts",
  "description": "Transcripts for the given calls. Mirrors POST /v2/calls/transcript.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "call_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200}
    },
    "required": ["call_ids"],
    "additionalProperties": false
  }
}
```

Returns `GongTranscriptResponse`. `sentences[].start` and `.end` are milliseconds. See the
assumption in `README.md`.

## Salesforce server: `mcp/salesforce_server.py`

### `sfdc_query_cases`

```json
{
  "name": "sfdc_query_cases",
  "description": "Cases created in a date range. Mirrors GET /services/data/v62.0/query with a SOQL SELECT over Case.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "created_from": {"type": "string", "description": "ISO 8601 with timezone, inclusive."},
      "created_to":   {"type": "string", "description": "ISO 8601 with timezone, inclusive."}
    },
    "required": ["created_from", "created_to"],
    "additionalProperties": false
  }
}
```

Returns `SalesforceQueryResponse` whose `records` are `Case` rows.

### `sfdc_get_case`

```json
{
  "name": "sfdc_get_case",
  "description": "One case with its PUBLISHED comments. Private comments are excluded by the SOQL, not filtered afterwards.",
  "inputSchema": {
    "type": "object",
    "properties": {"case_id": {"type": "string"}},
    "required": ["case_id"],
    "additionalProperties": false
  }
}
```

Returns `SalesforceCaseResponse`: `{case, comments, meta}`. `comments` contains only
`IsPublished = true` rows. `meta.withheld_comment_count` is how many were never in the
result set and `meta.soql` is the exact query, which contains the literal string
`IsPublished = true`. That string in that field is what makes the T4(a) control checkable by
grep rather than by trust.

### `sfdc_get_accounts`

```json
{
  "name": "sfdc_get_accounts",
  "description": "Account records including the org specific tier, ARR and renewal date custom fields.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "account_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200}
    },
    "required": ["account_ids"],
    "additionalProperties": false
  }
}
```

Returns `SalesforceQueryResponse` whose `records` are `Account` rows. Custom fields are
`Tier__c`, `ARR__c`, `Renewal_Date__c`, `Products__c`.

### `sfdc_get_users`

```json
{
  "name": "sfdc_get_users",
  "description": "User records for comment authors, so a connector can tell staff from a portal user.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "user_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200}
    },
    "required": ["user_ids"],
    "additionalProperties": false
  }
}
```

Returns `SalesforceQueryResponse` whose `records` are `User` rows with `Id`, `Name`,
`UserType`, `IsActive`.

This tool is an addition to the original three. It exists because `CaseComment.CreatedById`
does not say whether an author is a Momentive Software employee or a customer, and
`speaker_side` is not optional. `UserType = "Standard"` means staff; every other value
(`PowerPartner`, `CspLitePortal`, `CustomerSuccess`, `Guest`) is a portal or community user,
that is a client. A user id that does not resolve maps to `momentive`, because the safe
default is that an unidentified speaker is not a client.

## The response envelope

Every tool response carries `meta`:

```json
{
  "window": {"from": "2026-09-08T00:00:00Z", "to": "2026-09-08T23:59:59Z"},
  "rows_returned": 12,
  "row_cap": 200,
  "withheld_comment_count": 1,
  "fields_allowlisted": ["Id", "CaseNumber", "AccountId", "Subject", "Status", "Priority", "CreatedDate", "ClosedDate"],
  "soql": "SELECT ... FROM Case WHERE ... LIMIT 200"
}
```

- `window` is the server's configured window, not the request's.
- `withheld_comment_count` is `null` on every Gong response and an integer on every
  Salesforce response.
- `soql` is present on Salesforce responses only.
- `meta` is the MCP envelope, added by the server. A real API adapter drops it and fills the
  same fields from its own request context.

## The five enforcement rules, and how each is implemented

| # | Rule | Implementation | How it is proved |
|---|---|---|---|
| 1 | Read only | No write tool is registered. `list_tools` returns exactly the three Gong or four Salesforce names above | `grep` the server for a write verb; assert `list_tools` length and names |
| 2 | Date window scoping | The window comes from `DIGEST_WINDOW_FROM` and `DIGEST_WINDOW_TO` in the launcher's environment. A request outside it is REFUSED, not trimmed | A request one day outside returns the `window_violation` error, and `rows_returned` is never silently smaller |
| 3 | `IsPublished = true` in the query | The clause is in the SOQL string the server builds and returns in `meta.soql`. Private rows are read from disk only to be counted | Assert `IsPublished = true` is in `meta.soql`; assert no returned comment has `IsPublished` false; assert `withheld_comment_count` matches the corpus |
| 4 | Field allowlist | A per object list of field names; the server projects onto it and returns it in `meta.fields_allowlisted` | Assert the key set of every returned record equals the allowlist plus `attributes` |
| 5 | Row cap | `DIGEST_ROW_CAP`, default 200. Applied as `LIMIT` in SOQL and as a slice for Gong | Ask for a range containing more than the cap and assert exactly the cap comes back with a cursor |

### There is no `set_window` tool

The window is not negotiable at run time and there is deliberately no tool to change it.
It comes from the launcher's environment, which means it comes from the workflow file or the
Makefile, which means it is a diff on a pull request. An agent cannot widen its own scope.

### The `window_violation` error

A request outside the window returns an MCP tool error, not a result. The error payload:

```json
{
  "code": "window_violation",
  "message": "requested window is outside the window this server is configured for",
  "requested": {"from": "2026-09-01T00:00:00Z", "to": "2026-09-30T23:59:59Z"},
  "allowed":   {"from": "2026-09-08T00:00:00Z", "to": "2026-09-08T23:59:59Z"},
  "tool": "gong_list_calls"
}
```

The connector turns this into `digest.errors.WindowViolation(requested, allowed, tool)` and
`digest.audit` writes one event with `action: "reject"`, `outcome: "rejected"` and
`detail.code: "window_violation"`. Nothing is trimmed. Refusing loudly is the point: a
trimmed result looks exactly like a quiet day, and the worst outcome for a digest agent is
not an error, it is a digest that looks normal and is missing a day.

## Launching the servers

Both are stdio MCP servers. The pipeline launches them as subprocesses through the `mcp`
Python client and never leaves them running.

```
Gong:        python mcp/gong_server.py
Salesforce:  python mcp/salesforce_server.py
```

As an MCP client server spec:

```python
{
    "gong": {
        "command": sys.executable,
        "args": ["mcp/gong_server.py"],
        "env": {
            "DIGEST_MOCK_DIR": "data/mock",
            "DIGEST_WINDOW_FROM": "2026-09-08T00:00:00Z",
            "DIGEST_WINDOW_TO": "2026-09-08T23:59:59Z",
            "DIGEST_ROW_CAP": "200",
        },
    },
    "salesforce": {
        "command": sys.executable,
        "args": ["mcp/salesforce_server.py"],
        "env": {"...": "the same four"},
    },
}
```

### Environment read by both servers

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DIGEST_MOCK_DIR` | yes | none | Root of the mock corpus. The server reads `index.json` from here and resolves every `entries[].path` against it |
| `DIGEST_WINDOW_FROM` | yes | none | Inclusive start of the only window this process will serve. ISO 8601 with timezone |
| `DIGEST_WINDOW_TO` | yes | none | Inclusive end of the window |
| `DIGEST_ROW_CAP` | no | `200` | Maximum rows in any single response |

A server that starts with `DIGEST_WINDOW_FROM` or `DIGEST_WINDOW_TO` missing exits non zero
with a message naming the variable. Defaulting a security boundary to "everything" is how a
scoping control quietly stops existing.

### Which files each server reads

| Server | Reads |
|---|---|
| Gong | `index.json`, every `entries[].path` with `kind: gong_call` (under `gong/` and `traps/gong/`), `accounts.json` |
| Salesforce | `index.json`, every `entries[].path` with `kind: sfdc_case` (under `salesforce/` and `traps/salesforce/`), `accounts.json`, `salesforce/users.json` |

Trap files are loaded through the same code path as generated ones. A trap must be
indistinguishable from a generated fixture at read time, or it is testing the loader instead
of the pipeline.
