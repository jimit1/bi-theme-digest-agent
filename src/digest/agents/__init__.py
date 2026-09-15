"""Agent roles: prompts, schemas and call wrappers.

Every role under this package is a bounded role: one model tier, one input contract, one
output schema, one tool scope. Sub-packages: `readers` (`gong_reader`, `sfdc_reader`),
`editor`, `analyst`. Each also has a matching definition under `.claude/agents/` so the
same roles are runnable directly from Claude Code.
"""
from __future__ import annotations
