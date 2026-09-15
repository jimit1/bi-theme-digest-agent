"""Fixture data for tests/test_render.py: two themes, four claims, two source documents.

Two Gong claims come from one call (one mid-turn, with sentences on both sides, and one
single-sentence turn at the edge of the call so the neighbour-sentence lookup has to cross a
turn boundary). Two Salesforce claims come from one case's two comments. Each theme carries
one claim of each source, so both the markdown and the HTML renderer exercise both source
kinds in both themes.
"""
from __future__ import annotations

from typing import Any

GONG_SOURCE_ID = "7782934451099"
SFDC_CASE_ID = "500000000001234AAA"

GONG_DOC: dict[str, Any] = {
    "schema_version": "1.0.0",
    "source": "gong",
    "source_id": GONG_SOURCE_ID,
    "title": "Fixture account quarterly check in",
    "account_id": "ACC-0001",
    "account_name": "Fixture Museum Alliance",
    "occurred_at": "2026-09-08T15:00:00Z",
    "doc_type": "call",
    "ingest_run_id": "2026-09-08T06:00Z",
    "scrubbed": True,
    "pii_counts": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0},
    "participants": [
        {"id": "p-1", "name": "Dana Ruiz", "side": "client", "title": "Director of Membership"},
        {"id": "p-2", "name": "Marcus Feld", "side": "momentive", "title": "Client Success Manager"},
    ],
    "turns": [
        {
            "ref": {
                "call_id": GONG_SOURCE_ID,
                "speaker_id": "1",
                "speaker_name": "Dana Ruiz",
                "affiliation": "External",
                "start_ms": 65000,
                "end_ms": 90000,
            },
            "speaker_id": "1",
            "speaker_side": "client",
            "text": (
                "Sentence zero context. "
                "Our renewal invoice came through with no line for dues already paid. "
                "Trailing context sentence."
            ),
            "sentences": [
                {"start_ms": 65000, "end_ms": 70000, "text": "Sentence zero context."},
                {
                    "start_ms": 70000,
                    "end_ms": 85000,
                    "text": "Our renewal invoice came through with no line for dues already paid.",
                },
                {"start_ms": 85000, "end_ms": 90000, "text": "Trailing context sentence."},
            ],
        },
        {
            "ref": {
                "call_id": GONG_SOURCE_ID,
                "speaker_id": "1",
                "speaker_name": "Dana Ruiz",
                "affiliation": "External",
                "start_ms": 3670000,
                "end_ms": 3675000,
            },
            "speaker_id": "1",
            "speaker_side": "client",
            "text": "Single sign on provisioning drops staff role changes when they leave.",
            "sentences": [
                {
                    "start_ms": 3670000,
                    "end_ms": 3675000,
                    "text": "Single sign on provisioning drops staff role changes when they leave.",
                }
            ],
        },
    ],
    "meta": {"withheld_comment_count": 0, "turn_count": 2, "soql": None},
}

SFDC_DOC: dict[str, Any] = {
    "schema_version": "1.0.0",
    "source": "salesforce",
    "source_id": SFDC_CASE_ID,
    "title": "Case 00001099",
    "account_id": "ACC-0003",
    "account_name": "Fixture Land Trust Council",
    "occurred_at": "2026-09-09T13:58:41Z",
    "doc_type": "case",
    "ingest_run_id": "2026-09-09T06:00Z",
    "scrubbed": True,
    "pii_counts": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0},
    "participants": [
        {"id": "u-1", "name": "Priya Nair", "side": "client", "title": None},
        {"id": "u-2", "name": "Owen Clark", "side": "momentive", "title": "Support Engineer"},
    ],
    "turns": [
        {
            "ref": {
                "case_id": SFDC_CASE_ID,
                "case_number": "00001099",
                "comment_id": "00a000000000001AAA",
                "author_id": "005000000000001AAA",
                "author_name": "Priya Nair",
                "created_at": "2026-09-09T13:58:41Z",
            },
            "speaker_id": "u-1",
            "speaker_side": "client",
            "text": "Renewal credit still missing after last week's fix. Please escalate this.",
            "sentences": [],
        },
        {
            "ref": {
                "case_id": SFDC_CASE_ID,
                "case_number": "00001099",
                "comment_id": "00a000000000002AAA",
                "author_id": "005000000000001AAA",
                "author_name": "Priya Nair",
                "created_at": "2026-09-10T09:12:03Z",
            },
            "speaker_id": "u-1",
            "speaker_side": "client",
            "text": "Role changes from our identity provider are not syncing to membership records.",
            "sentences": [],
        },
    ],
    "meta": {"withheld_comment_count": 1, "turn_count": 2, "soql": "SELECT Id FROM CaseComment"},
}


def _claim(**kwargs: Any) -> dict[str, Any]:
    base = {
        "schema_version": "1.0.0",
        "run_id": "2026-09-14T07:00Z",
        "account_type": "customer",
        "speaker_side": "client",
        "paraphrase": "placeholder paraphrase",
        "topic": "renewal invoice credit",
        "product_area": "membership",
        "claim_type": "support_issue",
        "importance": "high",
        "importance_reason": "Finance has to correct the invoice by hand.",
        "captured_at": "2026-09-08T06:04:11.512Z",
        "prompt_hash": "80ab0b6e75c1789d",
        "model_tier": "extraction",
    }
    base.update(kwargs)
    return base


CLAIM_GONG_1 = _claim(
    claim_id="aaaaaaaaaaaa",
    source="gong",
    source_ref={
        "call_id": GONG_SOURCE_ID,
        "speaker_id": "1",
        "speaker_name": "Dana Ruiz",
        "affiliation": "External",
        "start_ms": 65000,
        "end_ms": 90000,
    },
    account_id="ACC-0001",
    account_name="Fixture Museum Alliance",
    account_type="customer",
    verbatim="Our renewal invoice came through with no line for dues already paid.",
)

CLAIM_GONG_2 = _claim(
    claim_id="bbbbbbbbbbbb",
    source="gong",
    source_ref={
        "call_id": GONG_SOURCE_ID,
        "speaker_id": "1",
        "speaker_name": "Dana Ruiz",
        "affiliation": "External",
        "start_ms": 3670000,
        "end_ms": 3675000,
    },
    account_id="ACC-0001",
    account_name="Fixture Museum Alliance",
    account_type="customer",
    verbatim="Single sign on provisioning drops staff role changes when they leave.",
    product_area="integrations",
    topic="SSO provisioning",
)

CLAIM_SFDC_1 = _claim(
    claim_id="cccccccccccc",
    source="salesforce",
    source_ref={
        "case_id": SFDC_CASE_ID,
        "case_number": "00001099",
        "comment_id": "00a000000000001AAA",
        "author_id": "005000000000001AAA",
        "author_name": "Priya Nair",
        "created_at": "2026-09-09T13:58:41Z",
    },
    account_id="ACC-0003",
    account_name="Fixture Land Trust Council",
    account_type="customer",
    verbatim="Renewal credit still missing after last week's fix.",
)

CLAIM_SFDC_2 = _claim(
    claim_id="dddddddddddd",
    source="salesforce",
    source_ref={
        "case_id": SFDC_CASE_ID,
        "case_number": "00001099",
        "comment_id": "00a000000000002AAA",
        "author_id": "005000000000001AAA",
        "author_name": "Priya Nair",
        "created_at": "2026-09-10T09:12:03Z",
    },
    account_id="ACC-0003",
    account_name="Fixture Land Trust Council",
    account_type="prospect",
    verbatim="Role changes from our identity provider are not syncing to membership records.",
    product_area="integrations",
    topic="SSO provisioning",
)

CLAIMS_BY_ID: dict[str, dict[str, Any]] = {
    c["claim_id"]: c for c in (CLAIM_GONG_1, CLAIM_GONG_2, CLAIM_SFDC_1, CLAIM_SFDC_2)
}

THEME_1: dict[str, Any] = {
    "schema_version": "1.0.0",
    "theme_id": "THEME-0001",
    "title": "Renewal invoices do not show prior dues credit",
    "aliases": ["dues proration", "credit on renewal"],
    "product_area": "membership",
    "status": "open",
    "owner": "ai-operations",
    "source": "synthesized",
    "last_verified": "2026-09-14",
    "run_id": "2026-09-14T07:00Z",
    "created_run": "2026-09-08T06:00Z",
    "last_updated_run": "2026-09-14T07:00Z",
    "accounts": ["ACC-0001", "ACC-0003"],
    "evidence": ["aaaaaaaaaaaa", "cccccccccccc"],
    "score": 75,
    "score_inputs": {
        "distinct_customers": 2,
        "distinct_prospects": 0,
        "arr_sum": 494000,
        "open_cases": 3,
        "recency_days": 1,
        "claim_count": 2,
        "high_importance_count": 2,
    },
    "rationale": "Two customers describe the same renewal invoice credit failure.",
    "stale": False,
    "stale_reason": None,
    "last_evidence_at": "2026-09-10T09:12:03.000Z",
    "proposal_id": "2026-W37/THEME-0001",
    "filed_issue_url": None,
}

THEME_2: dict[str, Any] = {
    "schema_version": "1.0.0",
    "theme_id": "THEME-0002",
    "title": "Single sign on provisioning drops staff role changes",
    "aliases": ["SSO provisioning", "SCIM sync"],
    "product_area": "integrations",
    "status": "quiet",
    "owner": "ai-operations",
    "source": "synthesized",
    "last_verified": "2026-08-20",
    "run_id": "2026-08-20T07:00Z",
    "created_run": "2026-08-20T07:00Z",
    "last_updated_run": "2026-08-20T07:00Z",
    "accounts": ["ACC-0001", "ACC-0003"],
    "evidence": ["bbbbbbbbbbbb", "dddddddddddd"],
    "score": 22,
    "score_inputs": {
        "distinct_customers": 1,
        "distinct_prospects": 1,
        "arr_sum": 120000,
        "open_cases": 1,
        "recency_days": 25,
        "claim_count": 2,
        "high_importance_count": 1,
    },
    "rationale": "Role changes made in the identity provider did not reach membership records.",
    "stale": True,
    "stale_reason": "last_verified is 25 days old, over the 14 day horizon",
    "last_evidence_at": "2026-08-20T10:00:00.000Z",
    "proposal_id": None,
    "filed_issue_url": None,
}

THEMES_RANKED = [THEME_1, THEME_2]

DIGEST: dict[str, Any] = {
    "headline": "Renewal invoice credit is now a two customer problem",
    "summary": "The renewal invoice credit theme picked up a second customer this week. SSO provisioning has gone quiet.",
    "sections": [
        {
            "theme_id_or_placeholder": "THEME-0001",
            "heading": "Renewal invoices do not show prior dues credit",
            "body": "Two customers now report the same renewal invoice failure, corrected by hand each time.",
            "evidence_claim_ids": ["aaaaaaaaaaaa", "cccccccccccc"],
        },
        {
            "theme_id_or_placeholder": "THEME-0002",
            "heading": "Single sign on provisioning drops staff role changes",
            "body": "No new evidence this week; the identity provider sync gap from last month stands.",
            "evidence_claim_ids": ["bbbbbbbbbbbb", "dddddddddddd"],
        },
    ],
    "reconciliations": [
        {
            "theme_id_or_placeholder": "THEME-0001",
            "names": ["dues proration", "credit on renewal"],
            "note": "Two product lineages use different names for the same credit line.",
        }
    ],
    "quiet_or_stale_notes": ["THEME-0002 has had no new evidence in over three weeks."],
}

MANIFEST: dict[str, Any] = {
    "schema_version": "1.0.0",
    "run_id": "2026-09-14T07:00Z",
    "run_type": "build",
    "week": "2026-W37",
    "mode": "replay",
    "started_at": "2026-09-14T07:00:00Z",
    "finished_at": "2026-09-14T07:02:41.004Z",
    "counts": {
        "sources_listed": 4,
        "sources_read": 4,
        "sources_skipped": 0,
        "comments_withheld": 1,
        "pii_redactions": 0,
        "claims_extracted": 5,
        "claims_verified": 4,
        "claims_rejected": 1,
        "themes_appended": 1,
        "themes_opened": 0,
        "themes_quiet": 1,
        "themes_stale": 1,
        "proposals_written": 1,
        "issues_filed": 0,
    },
    "rejected_by_reason": {
        "schema_invalid": 0,
        "citation_unresolved": 1,
        "speaker_not_client": 0,
        "duplicate": 0,
        "window_violation": 0,
    },
    "pii_redactions_by_kind": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0},
    "usage": {
        "by_stage": [
            {"stage": "extract", "calls": 4, "tokens_in": 8000, "tokens_out": 900,
             "cache_read": 0, "cache_write": 0, "cost_usd": 0.0125},
            {"stage": "edit", "calls": 2, "tokens_in": 4000, "tokens_out": 600,
             "cache_read": 0, "cache_write": 0, "cost_usd": 0.035},
        ],
        "by_tier": [
            {"tier": "extraction", "calls": 4, "tokens_in": 8000, "tokens_out": 900,
             "cache_read": 0, "cache_write": 0, "cost_usd": 0.0125},
            {"tier": "synthesis", "calls": 2, "tokens_in": 4000, "tokens_out": 600,
             "cache_read": 0, "cache_write": 0, "cost_usd": 0.035},
        ],
        "total": {"calls": 6, "tokens_in": 12000, "tokens_out": 1500,
                   "cache_read": 0, "cache_write": 0, "cost_usd": 0.0475},
    },
    "stability": {"computed": False, "jaccard": None, "top3_stable": None, "compared_run_id": None},
    "exit_code": 0,
}

PROPOSAL_FRONTMATTER: dict[str, Any] = {
    "schema_version": "1.0.0",
    "owner": "ai-operations",
    "source": "synthesized",
    "last_verified": "2026-09-14",
    "run_id": "2026-09-14T07:00Z",
    "theme_id": "THEME-0001",
    "week": "2026-W37",
    "status": "proposed",
    "filed_issue_url": None,
}

PROPOSAL_BODY = (
    "# Renewal invoices do not show prior dues credit\n\n"
    "Two customers, two independent reports, both ending in a manual finance correction.\n\n"
    "## Why it was proposed\n\n"
    "Two distinct customers, both high importance.\n"
)


class FakeStore:
    """The slice of `digest.store.Store`'s public API the renderer actually calls."""

    def __init__(self) -> None:
        self._sources = {GONG_SOURCE_ID: GONG_DOC, SFDC_CASE_ID: SFDC_DOC}

    def read_source_document(self, source_id: str) -> dict[str, Any]:
        from digest.errors import ContractViolation

        if source_id not in self._sources:
            raise ContractViolation("SourceDocument", ["no source document for %s" % source_id])
        return self._sources[source_id]

    def read_proposals(self, week: str) -> list[dict[str, Any]]:
        if week != "2026-W37":
            return []
        record = dict(PROPOSAL_FRONTMATTER)
        record["path"] = "proposals/2026-W37/THEME-0001.md"
        record["body"] = PROPOSAL_BODY
        return [record]
