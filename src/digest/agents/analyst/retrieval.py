"""Keyword retrieval over the theme store. No embeddings, no index build, no network.

`search_store` is the analyst's only way to see anything. It scores every theme in
`themes/_INDEX.md` by case folded token overlap between the question and the theme's
title, aliases, rationale and evidence table (which carries the account, the source and
the verbatim for every cited claim), then returns the top `k` as plain dicts the prompt
can render directly.

Reading a theme's body through `store.read_theme` is itself an audited action (see
`digest.store.Store.read_theme`), so a theme this function opens to score always leaves a
`read` event in the run log with no extra bookkeeping here. That is what "retrieval logs a
read audit event per theme touched" means in practice: touching is opening, and opening is
already logged by the store the analyst was handed.
"""
from __future__ import annotations

import re
from typing import Any

from digest.store import Store

__all__ = ["search_store"]

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_SNIPPET_WIDTH = 300

# Function words dropped before scoring, so two documents that only share "the" or "what"
# do not register as a match. This is the one deliberate departure from "every token counts
# equally": without it almost any question overlaps almost any theme, which defeats the
# point of a keyword score.
_STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before
being below between both but by can cannot could did do does doing down during each few
for from further get gets got had has have having he her here hers herself him himself his
how i if in into is it its itself just like me more most much my myself no nor not now of
off on once one only or other our ours ourselves out over own same say says said she should
so some such than that the their theirs them themselves then there these they this those
through to too under until up us very was we were what when where which while who whom why
will with would you your yours yourself yourselves
""".split())


def _tokens(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOPWORDS}


def _searchable_blob(theme: dict[str, Any], body: str) -> str:
    """Everything a question can match against: title, aliases, rationale, evidence body."""
    return "\n".join([
        theme.get("title", ""),
        " ".join(theme.get("aliases") or []),
        theme.get("rationale", ""),
        body,
    ])


def _best_line(blob: str, query_tokens: set[str]) -> str:
    best_line = ""
    best_hits = -1
    for line in blob.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        hits = len(_tokens(stripped) & query_tokens)
        if hits > best_hits:
            best_hits = hits
            best_line = stripped
    return best_line


def _snippet(blob: str, query_tokens: set[str], width: int = _SNIPPET_WIDTH) -> str:
    """At most `width` characters around the best matching line."""
    line = _best_line(blob, query_tokens)
    if len(line) <= width:
        return line
    lower = line.lower()
    pos = next((lower.find(tok) for tok in query_tokens if tok and lower.find(tok) != -1), 0)
    start = max(0, min(pos - width // 2, len(line) - width))
    return line[start:start + width].strip()


def search_store(store: Store, query: str, k: int = 5) -> list[dict[str, Any]]:
    """Score every theme against `query`, return the top `k`.

    Each result is {theme_id, title, score, snippet, claim_ids}. `score` is the number of
    distinct query tokens the theme matched; ties are broken by the theme's own stored
    `score` (business importance) descending, then `theme_id` ascending, so the same
    question returns the same themes every time. A theme with zero overlap is dropped
    rather than padded in, so an empty result is the honest answer to an off topic question.
    """
    query_tokens = _tokens(query)
    index = store.read_theme_index()
    scored: list[dict[str, Any]] = []
    for line in index:
        theme, body = store.read_theme(line["theme_id"])
        blob = _searchable_blob(theme, body)
        overlap = len(query_tokens & _tokens(blob))
        if overlap == 0:
            continue
        scored.append({
            "theme_id": theme["theme_id"],
            "title": theme["title"],
            "score": overlap,
            "snippet": _snippet(blob, query_tokens),
            "claim_ids": list(theme.get("evidence") or []),
            "_theme_score": int(line["score"]),
        })
    scored.sort(key=lambda item: (-item["score"], -item["_theme_score"], item["theme_id"]))
    return [{k2: v for k2, v in item.items() if k2 != "_theme_score"} for item in scored[:k]]
