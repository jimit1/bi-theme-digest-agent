"""The reader agents: `gong_reader` and `sfdc_reader`.

Both are the same code with a different prompt file. One scrubbed SourceDocument goes in,
one validated ReaderOutput comes out, on the `extraction` tier. No store, no tools, no
second document.
"""
from __future__ import annotations

from digest.agents.readers.reader import (
    SCHEMA_NAME,
    SOURCES,
    STAGE,
    TIER,
    agent_for,
    manifest,
    prompt_for,
    prompt_hash_of,
    prompt_meta,
    prompt_path,
    read_source,
    render_participants,
    render_turns,
    render_user,
)

__all__ = [
    "read_source",
    "prompt_for",
    "prompt_meta",
    "prompt_path",
    "prompt_hash_of",
    "render_user",
    "render_turns",
    "render_participants",
    "agent_for",
    "manifest",
    "SOURCES",
    "TIER",
    "SCHEMA_NAME",
    "STAGE",
]
