"""The deterministic theme score. No model touches this file.

Every input comes from the theme's evidence claims and their enrichment, never from a
model: `distinct_customers`/`distinct_prospects` from `Enrichment.account_type` on the
accounts the evidence claims cite, `arr_sum`/`open_cases` summed over the distinct customer
accounts, `recency_days` from the newest evidence claim's date, `claim_count` and
`high_importance_count` straight off the evidence list. `explain` re-derives the same five
formula terms from the stored inputs and prints them line by line, so a reviewer with only
the digest in front of them can recompute the score by hand.

Claim date, for `recency_days`: a Claim carries no `occurred_at` of its own (that belongs to
the source document, per `contracts/INTERFACES.md`'s `digest.enrich` section and the Claim
schema). For a Salesforce claim, `source_ref.created_at` (the cited comment's `CreatedDate`)
is an absolute calendar date and is used directly. For a Gong claim, `source_ref` carries
only `start_ms`/`end_ms`, offsets inside the call rather than an absolute time, so the source
date is unavailable and the claim falls back to its own `captured_at`, exactly as
`contracts/INTERFACES.md` describes for the one case where the source date does not exist.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, TypedDict

__all__ = ["ScoreInputs", "score", "explain", "rank"]


class ScoreInputs(TypedDict):
    distinct_customers: int
    distinct_prospects: int
    arr_sum: float
    open_cases: int
    recency_days: int
    claim_count: int
    high_importance_count: int


def _claim_date(claim: dict[str, Any]) -> _dt.date:
    if claim["source"] == "salesforce":
        raw = claim["source_ref"]["created_at"]
    else:
        raw = claim["captured_at"]
    return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()


def _score_inputs(theme: dict[str, Any], enrichment_by_account: dict[str, dict[str, Any]],
                   claims_by_id: dict[str, dict[str, Any]], as_of: _dt.date) -> ScoreInputs:
    claims = [claims_by_id[claim_id] for claim_id in theme["evidence"]]

    customer_accounts: set[str] = set()
    prospect_accounts: set[str] = set()
    for claim in claims:
        account_id = claim["account_id"]
        if enrichment_by_account[account_id]["account_type"] == "customer":
            customer_accounts.add(account_id)
        else:
            prospect_accounts.add(account_id)

    arr_sum = sum(enrichment_by_account[a]["arr_usd"] for a in customer_accounts)
    open_cases = sum(enrichment_by_account[a]["open_case_count"] for a in customer_accounts)
    newest_claim_date = max(_claim_date(claim) for claim in claims)
    recency_days = max(0, (as_of - newest_claim_date).days)

    return {
        "distinct_customers": len(customer_accounts),
        "distinct_prospects": len(prospect_accounts),
        "arr_sum": float(arr_sum),
        "open_cases": open_cases,
        "recency_days": recency_days,
        "claim_count": len(theme["evidence"]),
        "high_importance_count": sum(1 for c in claims if c["importance"] == "high"),
    }


def _terms(inputs: ScoreInputs) -> dict[str, float]:
    """The five formula terms plus the total and the clamped, rounded score.

    Single source of truth for the arithmetic: `score` and `explain` both call this, so
    they cannot drift apart from each other.
    """
    customers = 30 * min(inputs["distinct_customers"], 4) / 4
    value = 25 * min(inputs["arr_sum"], 500000) / 500000
    cases = 20 * min(inputs["open_cases"], 4) / 4
    recency = 15 * max(0, 14 - inputs["recency_days"]) / 14
    severity = 10 * min(inputs["high_importance_count"], 3) / 3
    total_before_penalty = customers + value + cases + recency + severity
    prospect_only = inputs["distinct_customers"] == 0
    total = total_before_penalty * 0.5 if prospect_only else total_before_penalty
    # floor(total + 0.5), not round(): half values always go up, so two implementations of
    # this formula cannot disagree with each other on a boundary case.
    rounded = int(math.floor(total + 0.5))
    rounded = max(0, min(100, rounded))
    return {
        "customers": customers,
        "value": value,
        "cases": cases,
        "recency": recency,
        "severity": severity,
        "total_before_penalty": total_before_penalty,
        "prospect_only": prospect_only,
        "total": total,
        "rounded": rounded,
    }


def score(theme: dict[str, Any], enrichment_by_account: dict[str, dict[str, Any]],
          claims_by_id: dict[str, dict[str, Any]], as_of: _dt.date) -> tuple[int, ScoreInputs]:
    """The theme's score, 0 through 100, and the seven inputs that produced it."""
    inputs = _score_inputs(theme, enrichment_by_account, claims_by_id, as_of)
    terms = _terms(inputs)
    return terms["rounded"], inputs


def explain(theme: dict[str, Any], inputs: ScoreInputs) -> str:
    """The arithmetic, line by line, so a reviewer can recompute the score by hand.

    Every one of the seven stored inputs appears in this string, in the line that uses it,
    along with the running total and the final score. This is the text that goes into the
    digest next to the theme.
    """
    terms = _terms(inputs)
    lines = [
        "score inputs for %s: distinct_customers=%d distinct_prospects=%d arr_sum=%.2f "
        "open_cases=%d recency_days=%d claim_count=%d high_importance_count=%d"
        % (theme["theme_id"], inputs["distinct_customers"], inputs["distinct_prospects"],
           inputs["arr_sum"], inputs["open_cases"], inputs["recency_days"],
           inputs["claim_count"], inputs["high_importance_count"]),
        "customers = 30 * min(%d, 4) / 4 = %.4f"
        % (inputs["distinct_customers"], terms["customers"]),
        "value = 25 * min(%.2f, 500000) / 500000 = %.4f" % (inputs["arr_sum"], terms["value"]),
        "cases = 20 * min(%d, 4) / 4 = %.4f" % (inputs["open_cases"], terms["cases"]),
        "recency = 15 * max(0, 14 - %d) / 14 = %.4f" % (inputs["recency_days"], terms["recency"]),
        "severity = 10 * min(%d, 3) / 3 = %.4f"
        % (inputs["high_importance_count"], terms["severity"]),
        "total = customers + value + cases + recency + severity = %.4f"
        % terms["total_before_penalty"],
    ]
    if terms["prospect_only"]:
        lines.append(
            "prospect only theme, no customer evidence yet (distinct_prospects=%d): "
            "total = total * 0.5 = %.4f" % (inputs["distinct_prospects"], terms["total"])
        )
    lines.append(
        "score = floor(total + 0.5) clamped to 0..100 = %d" % terms["rounded"]
    )
    return "\n".join(lines)


def rank(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Themes sorted by score descending, then distinct_customers descending, then theme_id
    ascending. The theme_id tiebreak is what makes two runs over the same input produce the
    same order."""
    return sorted(
        themes,
        key=lambda t: (
            -t["score"],
            -t["score_inputs"]["distinct_customers"],
            t["theme_id"],
        ),
    )
