"""The four read only things the editor can cause to be read.

There is no write tool in this module, and there is no write tool anywhere else that the
editor can reach. Not disabled, absent. Code validates the proposal and code performs every
write, because an agent holding a write tool would make the approval gate advisory.

The four are named exactly as `contracts/INTERFACES.md` names them so that `grep -r
read_theme_index` finds every place the editor can touch the store in one search. That is
the whole governance argument: the blast radius is four functions long and a reviewer can
read all four in a minute.

Each one writes its own audit event with `action: "read"`. The tool logs it rather than the
caller, because a caller that has to remember eventually forgets, and "what did the editor
touch this run" has to be a query over the run log rather than a guess.
"""
from __future__ import annotations

from typing import Any, Iterable

from digest.contracts import validate
from digest.errors import ContractViolation

__all__ = ["EditorTools", "TOOL_NAMES", "EDITOR_AGENT", "EDITOR_STAGE"]

# The agent name every editor audit event carries, and the stage those events belong to.
# `edit` is one of the fixed stage names in contracts/file_formats.md section 14. A store
# read made on the editor's behalf is attributed to the editor's stage rather than to
# `store`, so the cost and activity table answers "what did the edit stage touch".
EDITOR_AGENT = "editor"
EDITOR_STAGE = "edit"

#: The complete tool surface. Four names, all read only. Nothing is added at runtime.
TOOL_NAMES = ("read_theme_index", "read_theme", "list_run_claims", "read_account")


class EditorTools:
    """The editor's read only surface, bound to one store, one run and one week.

    The two calls in `digest.agents.editor.editor` go through this object for every read,
    which is why the run log can say exactly which themes were opened without depending on
    a model choosing to announce it.

    `claims` and `enrichment` are the verified claims and the deterministic enrichment the
    pipeline already computed for this week. They are passed in rather than re read so the
    editor sees exactly what the verifier let through; when they are not passed, the tools
    fall back to the store, which is what makes them usable on their own.
    """

    def __init__(self, store: Any, audit: Any, week: str,
                 claims: Iterable[dict[str, Any]] | None = None,
                 enrichment: dict[str, dict[str, Any]] | None = None) -> None:
        self.store = store
        self.audit = audit
        self.week = week
        self._claims = None if claims is None else [dict(c) for c in claims]
        self._enrichment = None if enrichment is None else dict(enrichment)

    # -- the four -----------------------------------------------------------------

    def read_theme_index(self) -> list[dict[str, Any]]:
        """Layer 1: one line per theme. The first thing the editor sees, every run."""
        lines = self.store.read_theme_index()
        self._log("themes/_INDEX.md", {"themes": len(lines)})
        return [dict(line) for line in lines]

    def read_theme(self, theme_id: str) -> tuple[dict[str, Any], str]:
        """One theme in full: its frontmatter and its markdown body.

        Called by code for each id the editor asked for in call one. An id that is not in
        the index never reaches here; `run_editor` drops it with a reject event instead.
        """
        theme, body = self.store.read_theme(theme_id)
        self._log(theme_id, {"evidence": len(theme.get("evidence") or []),
                             "body_chars": len(body)})
        return theme, body

    def list_run_claims(self) -> list[dict[str, Any]]:
        """This week's verified claims, from the ingest runs that belong to the week."""
        if self._claims is None:
            self._claims = [dict(c) for c in self.store.read_claims(week=self.week)]
        self._log("evidence/claims", {"week": self.week, "claims": len(self._claims)})
        return [dict(c) for c in self._claims]

    def read_account(self, account_id: str) -> dict[str, Any]:
        """The deterministic enrichment for one account: tier, ARR, open cases, products.

        Validated on the way out. The editor is told not to invent numbers, and handing it
        a document nobody checked would make that instruction the only safeguard.
        """
        if self._enrichment is None:
            raise ContractViolation(
                "Enrichment",
                ["$: no enrichment was supplied to EditorTools, so %s cannot be read"
                 % account_id],
            )
        try:
            record = self._enrichment[account_id]
        except KeyError:
            raise ContractViolation(
                "Enrichment",
                ["$: no enrichment for account %s in this run" % account_id],
            ) from None
        validate(record, "Enrichment")
        self._log(account_id, {"account_type": record.get("account_type")})
        return dict(record)

    # -- audit --------------------------------------------------------------------

    def _log(self, target: str, detail: dict[str, Any] | None = None) -> None:
        if self.audit is None:
            return
        self.audit.log(agent=EDITOR_AGENT, action="read", stage=EDITOR_STAGE,
                       target=target, detail=dict(detail or {}))
