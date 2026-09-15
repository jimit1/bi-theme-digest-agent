"""The editor: the one place in this system where a frontier model is asked for judgment.

Everything else is deterministic. The editor decides whether a claim is the same underlying
problem as a theme that already exists, or something genuinely new, and says why in a
sentence a product manager would accept. It writes the digest prose. It proposes what to
file. It computes no score and it performs no write.

Two calls, not a tool loop. Call one names the themes it needs opened; code opens them and
logs a read event for each. Call two returns an EditorProposal, which code validates against
the contract and then cross checks against this run's claims and the theme index before a
single byte reaches the store.
"""
from __future__ import annotations

from digest.agents.editor.editor import (
    EDITOR_PROMPT,
    THEME_REQUEST_PROMPT,
    PromptFile,
    build_date_for_week,
    load_prompt,
    manifest,
    quiet_or_stale_themes,
    run_editor,
    run_id_for_week,
    validate_proposal,
)
from digest.agents.editor.tools import TOOL_NAMES, EditorTools

__all__ = [
    "EditorTools",
    "TOOL_NAMES",
    "PromptFile",
    "EDITOR_PROMPT",
    "THEME_REQUEST_PROMPT",
    "load_prompt",
    "manifest",
    "run_editor",
    "validate_proposal",
    "quiet_or_stale_themes",
    "build_date_for_week",
    "run_id_for_week",
]
