"""The analyst: a grounded question and answer role with no source access.

The analyst reads the theme store and nothing else. `retrieval.search_store` does the
keyword lookup over `themes/_INDEX.md` and the individual theme files; `analyst.ask` turns
one question into one call on tier `narrative`, validated against `AnalystAnswer`. If the
store does not support an answer, the answer says so instead of guessing.
"""
from __future__ import annotations

from digest.agents.analyst.analyst import ask
from digest.agents.analyst.retrieval import search_store

__all__ = ["ask", "search_store"]
