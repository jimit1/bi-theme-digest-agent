"""The analyst: one question in, one grounded AnalystAnswer out.

The analyst has no source access at all. It never opens a Gong call or a Salesforce case;
it sees only what `digest.agents.analyst.retrieval.search_store` returns from the theme
store, which is already scrubbed and already summarised by the editor. `ask` renders the
retrieved themes into the prompt's user template, asks the router for tier `narrative`
(there are only three runtime tiers: extraction, synthesis, narrative; "analyst" is a role,
not a tier), and returns whatever the router validated against `AnalystAnswer`. The schema
itself enforces the two directions: an unsupported answer cannot smuggle citations and a
supported one cannot arrive without any.
"""
from __future__ import annotations

import functools
import pathlib
import re
from typing import Any

from digest.agents.analyst.retrieval import search_store
from digest.errors import ContractViolation
from digest.router import Router
from digest.store import Store

__all__ = ["ask", "TIER", "SCHEMA_NAME", "AGENT", "RETRIEVAL_LIMIT", "prompt_for"]

PROMPT_PATH = pathlib.Path(__file__).resolve().parent / "analyst.prompt.md"

TIER = "narrative"
SCHEMA_NAME = "AnalystAnswer"
AGENT = "analyst"
RETRIEVAL_LIMIT = 5

# `---` alone on its own line. Frontmatter, then the system prompt, then the user template,
# the same three way split the reader prompts use, so a prompt file is versioned and
# reviewable the same way everywhere in this repository.
_SEPARATOR = re.compile(r"^---[ \t]*$", re.MULTILINE)

NO_CONTEXT = "(no theme in the store matched this question)"


@functools.lru_cache(maxsize=None)
def _load_prompt() -> tuple[dict[str, Any], str, str]:
    try:
        raw = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractViolation(
            "AnalystPrompt", ["$: cannot read %s: %s" % (PROMPT_PATH, exc)]
        ) from exc
    parts = _SEPARATOR.split(raw)
    if len(parts) != 4 or parts[0].strip():
        raise ContractViolation(
            "AnalystPrompt",
            ["$: %s must be frontmatter, system prompt and user template, separated by "
             "three lines of exactly ---" % PROMPT_PATH],
        )
    import yaml

    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ContractViolation("AnalystPrompt", ["$: %s frontmatter is not a mapping" % PROMPT_PATH])
    if meta.get("schema") != SCHEMA_NAME or meta.get("tier") != TIER:
        raise ContractViolation(
            "AnalystPrompt",
            ["$: %s asks for schema %r tier %r, the analyst role is schema %r tier %r"
             % (PROMPT_PATH, meta.get("schema"), meta.get("tier"), SCHEMA_NAME, TIER)],
        )
    return meta, parts[2].strip(), parts[3].strip()


def prompt_for() -> tuple[str, str]:
    """(system prompt, user template) for the analyst. Kept public so a test can assert on it."""
    _, system, template = _load_prompt()
    return system, template


def _evidence_block(store: Store, hit: dict[str, Any]) -> str:
    """Render one retrieved theme: its title, its rationale and its evidence table.

    `read_theme` is what actually opens the file, and that call is what leaves the `read`
    audit event for this theme in the run log; nothing here logs a second one.
    """
    theme, body = store.read_theme(hit["theme_id"])
    return "Theme %s: %s\n%s" % (hit["theme_id"], theme["title"], body.strip())


def _render_context(store: Store, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return NO_CONTEXT
    return "\n\n".join(_evidence_block(store, hit) for hit in hits)


def ask(question: str, store: Store, router: Router, audit: Any) -> dict[str, Any]:
    """Answer `question` from the theme store alone. Returns a validated AnalystAnswer.

    The store is attached to `audit` before retrieval runs, so every theme retrieval opens
    to score is logged under this run rather than silently. Retrieval always runs, even when
    it finds nothing: the model is the one that writes `decline_reason`, from context that
    plainly says there was nothing to find, rather than code guessing at the wording.
    """
    store.attach_audit(audit)
    hits = search_store(store, question, k=RETRIEVAL_LIMIT)
    system, template = prompt_for()
    user = template.format(question=question, context=_render_context(store, hits))
    run_id = getattr(audit, "run_id")
    result = router.complete(TIER, system, user, SCHEMA_NAME,
                             run_id=run_id, agent=AGENT, audit=audit)
    return result["data"]
