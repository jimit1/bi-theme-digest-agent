"""Source connectors. One file per source, one protocol, no pipeline branch.

The pipeline never opens a mock file directly: it calls a tool on one of the two local
MCP servers, which enforce read only access, the date window, the published comment
filter, the field allowlist and the row cap at the boundary rather than in a prompt.
Adding Zendesk or a community forum would be one more file in here plus a config entry.
"""
from __future__ import annotations

from digest.connectors.base import (
    AccountDirectory,
    SourceConnector,
    SourceRef,
    day_bounds,
    format_instant,
    ingest_run_id_for,
    parse_instant,
)
from digest.connectors.gong import GongConnector
from digest.connectors.mcp_client import (
    SERVER_SCRIPTS,
    McpToolClient,
    repo_root,
    server_spec,
)
from digest.connectors.salesforce import SalesforceConnector

__all__ = [
    "AccountDirectory",
    "GongConnector",
    "McpToolClient",
    "SERVER_SCRIPTS",
    "SalesforceConnector",
    "SourceConnector",
    "SourceRef",
    "day_bounds",
    "format_instant",
    "ingest_run_id_for",
    "parse_instant",
    "repo_root",
    "server_spec",
]
