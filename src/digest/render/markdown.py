"""The plain-markdown weekly digest: `render_markdown`.

Signature note (recorded for the orchestrator): `contracts/INTERFACES.md` documents
`digest.render.render_markdown` as `(week, themes, claims, manifest, store) -> str`, taking
one flat claims list and no separate parameter for the editor's headline, summary,
reconciliations, quiet/stale notes or filing proposals. Those live in `EditorProposal.digest`
(`contracts/EditorProposal.schema.json`) and there is no way to reach them through the
documented signature alone, since `Theme.schema.json` and `RunManifest.schema.json` are both
`additionalProperties: false` and neither carries them. `build/briefs/B13.md` specifies the
signature actually implemented here: `render_markdown(week, digest, themes_ranked,
claims_by_id, manifest, store)`, where `digest` is that `EditorProposal.digest` sub-object
and `claims_by_id` is a `claim_id -> Claim` map (the brief's own choice, sized for repeated
per-theme evidence lookups instead of a linear scan of a flat list). This file follows the
brief. Flagged in the B13 envelope under `assumptions` so `INTERFACES.md` and the caller in
`digest.pipeline` (B16) can be reconciled.
"""
from __future__ import annotations

import re
from typing import Any

from digest.render.citations import citation_label
from digest.render.scoring import explain_score
from digest.store import Store

__all__ = ["render_markdown"]

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def render_markdown(
    week: str,
    digest: dict[str, Any],
    themes_ranked: list[dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    store: Store,
) -> str:
    ordered = sorted(themes_ranked, key=lambda t: (-int(t["score"]), t["theme_id"]))
    sections_by_theme = {s["theme_id_or_placeholder"]: s for s in digest.get("sections", [])}

    lines: list[str] = []
    lines.append("# Theme digest, week %s" % week)
    lines.append("")
    lines.append(_run_line(manifest))
    lines.append("")
    lines.append("## %s" % digest["headline"])
    lines.append("")
    lines.append(digest["summary"])
    lines.append("")

    for position, theme in enumerate(ordered, start=1):
        lines.extend(_theme_section(position, theme, sections_by_theme, claims_by_id))
        lines.append("")

    lines.append("## Reconciliations")
    lines.append("")
    reconciliations = digest.get("reconciliations", [])
    if not reconciliations:
        lines.append("None this run.")
    else:
        for item in reconciliations:
            names = ", ".join('"%s"' % n for n in item["names"])
            lines.append(
                "- %s: %s are the same thing. %s"
                % (item["theme_id_or_placeholder"], names, item["note"])
            )
    lines.append("")

    lines.append("## Quiet and stale")
    lines.append("")
    lines.extend(_quiet_and_stale(ordered, digest.get("quiet_or_stale_notes", [])))
    lines.append("")

    lines.append("## Proposed for filing")
    lines.append("")
    lines.extend(_proposed_for_filing(week, store))
    lines.append("")

    lines.append("## How to trace a claim by hand")
    lines.append("")
    lines.append(
        "Open sources/<source_id>.json in the store, using the id in the citation label "
        "in brackets (the call id for a Gong moment, the case id for a Salesforce one). "
        "Find the turn whose ref matches the claim's source_ref, then find the verbatim "
        "text quoted above as an exact substring of that turn's text."
    )

    return "\n".join(lines).rstrip("\n") + "\n"


def _run_line(manifest: dict[str, Any]) -> str:
    """One line a reader can check the week against.

    The numbers here are the week's, not the build run's. A build reads no sources and
    verifies no claims of its own, so `digest.pipeline.week_summary` adds up the week's
    ingest runs plus this build and hands the result in through this same argument. A plain
    RunManifest still renders, without the call and case split and without the weekly cost.
    """
    counts = manifest["counts"]
    usage = manifest["usage"]
    tiers = ", ".join(sorted(row["tier"] for row in usage.get("by_tier", []))) or "none"
    by_doc_type = manifest.get("sources_by_doc_type")
    sources = "%d sources read" % counts["sources_read"]
    if by_doc_type is not None:
        sources += " (%d calls, %d cases)" % (by_doc_type.get("call", 0),
                                              by_doc_type.get("case", 0))
    cost = usage["total"]["cost_usd"]
    build_cost = manifest.get("build_cost_usd")
    cost_text = ("cost $%.2f for the week ($%.2f this build)" % (cost, build_cost)
                 if build_cost is not None else "cost $%.2f" % cost)
    scope = ("Run %s, week %s" % (manifest["run_id"], manifest["week"])
             if by_doc_type is not None and manifest.get("week")
             else "Run %s" % manifest["run_id"])
    return (
        "%s: %s, %d private comments withheld, %d PII redactions, "
        "%d claims verified, %d rejected, %d themes appended, %d opened, %s, "
        "model tiers used: %s."
        % (
            scope,
            sources,
            counts["comments_withheld"],
            counts["pii_redactions"],
            counts["claims_verified"],
            counts["claims_rejected"],
            counts["themes_appended"],
            counts["themes_opened"],
            cost_text,
            tiers,
        )
    )


def _theme_section(
    position: int,
    theme: dict[str, Any],
    sections_by_theme: dict[str, dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    lines.append("### %d. %s (score %d)" % (position, theme["title"], theme["score"]))
    lines.append("")
    lines.append(_status_line(theme))
    lines.append("")

    section = sections_by_theme.get(theme["theme_id"])
    body = section["body"] if section is not None else theme["rationale"]
    lines.append(body)
    lines.append("")

    lines.append("Evidence:")
    for claim_id in theme["evidence"]:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            lines.append('- claim %s is not in this run\'s claim map [%s]' % (claim_id, claim_id))
            continue
        lines.append(
            '- "%s" : %s (%s), %s [%s]'
            % (
                claim["verbatim"],
                claim["account_name"],
                claim["account_type"],
                citation_label(claim),
                claim_id,
            )
        )
    lines.append("")

    lines.append(_why_this_score(theme))
    return lines


def _status_line(theme: dict[str, Any]) -> str:
    inputs = theme["score_inputs"]
    parts = [
        "Accounts: %d customer, %d prospect."
        % (inputs["distinct_customers"], inputs["distinct_prospects"]),
        "Open cases on these accounts: %d." % inputs["open_cases"],
        "Last evidence: %s." % theme["last_evidence_at"][:10],
        "Status: %s." % theme["status"],
    ]
    if theme["status"] == "quiet":
        parts.append(
            "QUIET: no new evidence and the newest is %d days old." % inputs["recency_days"]
        )
    if theme["stale"]:
        parts.append("STALE: %s" % theme["stale_reason"])
    return " ".join(parts)


def _why_this_score(theme: dict[str, Any]) -> str:
    explained = explain_score(theme["score_inputs"])
    terms = " + ".join("%s %s = %.2f" % (name, formula, value) for name, formula, value in explained["terms"])
    penalty_note = " (prospect-only theme, halved)" if explained["penalty"] else ""
    return "Why this score: %s -> %.2f%s -> floor(+0.5), clamped: %d." % (
        terms,
        explained["total"],
        penalty_note,
        explained["score"],
    )


def _quiet_and_stale(ordered: list[dict[str, Any]], notes: list[str]) -> list[str]:
    lines: list[str] = []
    for theme in ordered:
        if theme["status"] == "quiet":
            lines.append(
                "- %s: quiet, newest evidence %d days old."
                % (theme["title"], theme["score_inputs"]["recency_days"])
            )
        if theme["stale"]:
            lines.append("- %s: stale, %s" % (theme["title"], theme["stale_reason"]))
    for note in notes:
        lines.append("- %s" % note)
    if not lines:
        lines.append("Nothing quiet or stale this run.")
    return lines


def _proposed_for_filing(week: str, store: Store) -> list[str]:
    proposals = store.read_proposals(week)
    if not proposals:
        return ["No proposals filed this week."]
    lines: list[str] = []
    for proposal in proposals:
        match = _TITLE_RE.search(proposal.get("body", ""))
        title = match.group(1) if match else proposal["theme_id"]
        lines.append(
            '- %s "%s": status %s'
            % (proposal["theme_id"], title, proposal["status"])
        )
    return lines
