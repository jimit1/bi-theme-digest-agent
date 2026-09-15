"""Recompute the score arithmetic from a theme's stored `score_inputs`, for display only.

`digest.score` (per contracts/INTERFACES.md) is the module that computes a score in the
first place; there is no `digest.score` file in this checkout yet, and even once there is,
the renderer's job is to show the reviewer the same arithmetic that produced the number
already stored on the theme, not to recompute a score that gets used for anything. The
formula here is copied verbatim from contracts/INTERFACES.md ("The formula, fixed") and from
contracts/file_formats.md, which both pin it to the same five terms and the same rounding
rule. Keep this in sync with `digest.score` if that module's formula ever changes; the
`schema_version` on Theme.score_inputs would bump first.
"""
from __future__ import annotations

import math
from typing import Any

__all__ = ["explain_score"]


def explain_score(score_inputs: dict[str, Any]) -> dict[str, Any]:
    """Return the five weighted terms, the prospect penalty flag, and the final score."""
    distinct_customers = score_inputs["distinct_customers"]
    distinct_prospects = score_inputs["distinct_prospects"]
    arr_sum = score_inputs["arr_sum"]
    open_cases = score_inputs["open_cases"]
    recency_days = score_inputs["recency_days"]
    high_importance_count = score_inputs["high_importance_count"]

    customers = 30 * min(distinct_customers, 4) / 4
    value = 25 * min(arr_sum, 500000) / 500000
    cases = 20 * min(open_cases, 4) / 4
    recency = 15 * max(0, 14 - recency_days) / 14
    severity = 10 * min(high_importance_count, 3) / 3

    subtotal = customers + value + cases + recency + severity
    penalty = distinct_customers == 0
    total = subtotal * 0.5 if penalty else subtotal
    score = int(math.floor(total + 0.5))
    score = max(0, min(100, score))

    return {
        "terms": [
            ("customers", "30 * min(%d, 4) / 4" % distinct_customers, customers),
            ("value", "25 * min(%s, 500000) / 500000" % _fmt_num(arr_sum), value),
            ("cases", "20 * min(%d, 4) / 4" % open_cases, cases),
            ("recency", "15 * max(0, 14 - %d) / 14" % recency_days, recency),
            ("severity", "10 * min(%d, 3) / 3" % high_importance_count, severity),
        ],
        "subtotal": subtotal,
        "penalty": penalty,
        "distinct_prospects": distinct_prospects,
        "total": total,
        "score": score,
    }


def _fmt_num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
