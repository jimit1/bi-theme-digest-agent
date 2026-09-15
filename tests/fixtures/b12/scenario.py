"""The B12 editor fixture: one week, two existing themes, eight verified claims.

Built in code rather than checked in as markdown so that every claim id is the real
sha256 the contract defines, and so the store on disk is produced by the store's own
writer. A hand written fixture drifts from the format the moment the format changes.

The eight claims are chosen to exercise the judgment the editor exists for:

  - two renewal billing claims from two different accounts with no shared vocabulary
    beyond the word invoice, which must land on one theme
  - two offline event claims, one saying "event check-in" and one saying "the attendee
    kiosk", which must land on one theme carrying both names
  - two pledge reminder claims from two different accounts, one about a frequency the
    donor did not ask for and one about a channel the donor opted out of, which are two
    facets of one behaviour and must land on one theme
  - one claim from a prospect, which must be decided and must not be dressed up as
    customer evidence
  - one claim that plainly belongs to a theme the store already has, which must be an
    append rather than a new theme

Every organisation, person and record here is fictional.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

WEEK = "2026-W37"
RUN_ID = "2026-09-14T07:00Z"
INGEST_RUN = "2026-09-11T06:00Z"
PRIOR_RUN = "2026-09-07T07:00Z"
QUIET_RUN = "2026-08-24T07:00Z"
PROMPT_HASH = "0123456789abcdef"


def claim_id(source_ref: dict[str, Any], verbatim: str) -> str:
    """contracts/file_formats.md section 1, verbatim. The fixture proves the rule too."""
    digest = hashlib.sha256()
    digest.update(json.dumps(source_ref, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8"))
    digest.update(verbatim.encode("utf-8"))
    return digest.hexdigest()[:12]


def _gong_ref(call_id: str, speaker_id: str, speaker_name: str, start_ms: int) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "speaker_id": speaker_id,
        "speaker_name": speaker_name,
        "affiliation": "External",
        "start_ms": start_ms,
        "end_ms": start_ms + 21000,
    }


def _case_ref(case_id: str, case_number: str, comment_id: str, author_id: str,
              author_name: str, created_at: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "case_number": case_number,
        "comment_id": comment_id,
        "author_id": author_id,
        "author_name": author_name,
        "created_at": created_at,
    }


def _claim(source: str, source_ref: dict[str, Any], account_id: str, account_name: str,
           account_type: str, verbatim: str, paraphrase: str, topic: str, product_area: str,
           claim_type: str, importance: str, importance_reason: str, captured_at: str,
           run_id: str = INGEST_RUN) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "claim_id": claim_id(source_ref, verbatim),
        "run_id": run_id,
        "source": source,
        "source_ref": source_ref,
        "account_id": account_id,
        "account_name": account_name,
        "account_type": account_type,
        "speaker_side": "client",
        "verbatim": verbatim,
        "paraphrase": paraphrase,
        "topic": topic,
        "product_area": product_area,
        "claim_type": claim_type,
        "importance": importance,
        "importance_reason": importance_reason,
        "captured_at": captured_at,
        "prompt_hash": PROMPT_HASH,
        "model_tier": "extraction",
    }


# --------------------------------------------------------------------------- prior claims

PRIOR_CLAIMS: list[dict[str, Any]] = [
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934450901", "5510", "Beatrix Nnamdi", 412000),
        account_id="ACC-0002", account_name="Cascadia Nurses Association",
        account_type="customer",
        verbatim="Anything over ten thousand rows comes back cut off and we never get a warning that it happened.",
        paraphrase="Exports above ten thousand rows are silently truncated with no warning.",
        topic="report export row cap", product_area="reporting",
        claim_type="support_issue", importance="high",
        importance_reason="Staff acted on an incomplete export before anyone noticed.",
        captured_at="2026-09-02T15:04:11Z", run_id="2026-09-02T06:00Z"),
    _claim(
        source="salesforce",
        source_ref=_case_ref("5008W00002aQpKmQAK", "00010388", "00a8W00001bQmSyQAK",
                             "0058W00000jLpQrQAK", "Odalys Fernwright",
                             "2026-08-19T11:22:03Z"),
        account_id="ACC-0005", account_name="Sunbelt Literacy Network",
        account_type="customer",
        verbatim="The journal entries from last month never posted to the general ledger, so our books are out by that amount.",
        paraphrase="Last month's journal entries never posted to the general ledger.",
        topic="general ledger posting", product_area="accounting",
        claim_type="support_issue", importance="medium",
        importance_reason="Finance closed the month with a known gap.",
        captured_at="2026-08-19T11:22:03Z", run_id="2026-08-19T06:00Z"),
]

# --------------------------------------------------------------------------- this week

RUN_CLAIMS: list[dict[str, Any]] = [
    # The T1 pair: one billing failure, two vocabularies, two accounts.
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934451002", "6201", "Rosalind Achebe", 754000),
        account_id="ACC-0001", account_name="Great Lakes Museum Alliance",
        account_type="customer",
        verbatim="The renewal statement that went out last week is missing the amount we already carried over from the previous period, so the total is wrong before anyone even looks at it.",
        paraphrase="Renewal statements leave out the amount carried over from the previous period, so the total is wrong.",
        topic="renewal statement totals", product_area="membership",
        claim_type="support_issue", importance="high",
        importance_reason="Every renewal statement in the batch went out with a wrong total.",
        captured_at="2026-09-08T16:31:52Z"),
    _claim(
        source="salesforce",
        source_ref=_case_ref("5008W00002aQpLrQAK", "00010423", "00a8W00001bQmTzQAK",
                             "0058W00000jLpRsQAK", "Nadia Brightwater",
                             "2026-09-09T09:47:20Z"),
        account_id="ACC-0003", account_name="Prairie Land Trust Council",
        account_type="customer",
        verbatim="Members who upgraded in the middle of the year are being billed the full amount again with nothing knocked off, and finance has to fix every one of them by hand.",
        paraphrase="Members who upgrade mid year are billed the full amount again and finance corrects each invoice by hand.",
        topic="mid year upgrade billing", product_area="membership",
        claim_type="support_issue", importance="high",
        importance_reason="Finance is hand correcting every affected invoice before it goes out.",
        captured_at="2026-09-09T09:47:20Z"),
    # The T2 pair: one capability, two product names.
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934451118", "6344", "Bernard Toussaint", 288000),
        account_id="ACC-0002", account_name="Cascadia Nurses Association",
        account_type="customer",
        verbatim="Our event check-in has to keep working when the venue wifi drops, and then sync everything up once we are back online.",
        paraphrase="Event check-in needs to keep working when venue wifi drops and sync once connectivity returns.",
        topic="event check-in offline", product_area="events",
        claim_type="feature_request", importance="high",
        importance_reason="A wifi drop at their last conference stopped admissions at the door.",
        captured_at="2026-09-09T14:12:05Z"),
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934451207", "6412", "Marguerite Delacroix", 521000),
        account_id="ACC-0004", account_name="Atlantic Shipwrights Guild",
        account_type="customer",
        verbatim="On our previous platform the attendee kiosk stayed up when the wifi went down, and we need the attendee kiosk to do the same here.",
        paraphrase="The attendee kiosk must stay usable through a wifi outage, as it did on their previous platform.",
        topic="attendee kiosk offline", product_area="events",
        claim_type="feature_request", importance="medium",
        importance_reason="They ran this way on their previous platform and expect parity.",
        captured_at="2026-09-10T10:05:44Z"),
    # A prospect. Real signal, not customer evidence.
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934451311", "6588", "Idris Vanterpool", 199000),
        account_id="ACC-0007", account_name="Northwoods Arborists Society",
        account_type="prospect",
        verbatim="We need to be able to upload SCORM 1.2 and SCORM 2004 packages into the learning platform without repackaging them first.",
        paraphrase="Wants SCORM 1.2 and SCORM 2004 package upload in the learning platform without repackaging.",
        topic="SCORM package upload", product_area="lms",
        claim_type="feature_request", importance="medium",
        importance_reason="Named as a requirement in an active evaluation.",
        captured_at="2026-09-10T13:40:19Z"),
    # The over-splitting pair: one behaviour, two facets of it. The platform ignores the
    # communication preference a donor set on pledge reminders. One account meets it as a
    # frequency it did not ask for, the other as a channel it opted out of. A fix to the
    # preference check fixes both, so this is ONE theme and not two.
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934451402", "6703", "Philippa Mbeki", 645000),
        account_id="ACC-0005", account_name="Sunbelt Literacy Network",
        account_type="customer",
        verbatim="We set this donor down for one pledge reminder a year and the system sent her four of them anyway.",
        paraphrase="Pledge reminders go out more often than the donor asked for.",
        topic="pledge reminder frequency", product_area="fundraising",
        claim_type="support_issue", importance="high",
        importance_reason="Donors are complaining directly to the development office.",
        captured_at="2026-09-10T15:18:27Z"),
    _claim(
        source="salesforce",
        source_ref=_case_ref("5008W00002aQpMvQAK", "00010451", "00a8W00001bQmUxQAK",
                             "0058W00000jLpStQAK", "Caspian Rowntree",
                             "2026-09-11T10:02:14Z"),
        account_id="ACC-0001", account_name="Great Lakes Museum Alliance",
        account_type="customer",
        verbatim="Donors who chose paper only are still getting the pledge reminder emails, which is exactly what they told us they did not want.",
        paraphrase="Pledge reminder emails reach donors who opted for paper only.",
        topic="pledge reminder channel preference", product_area="fundraising",
        claim_type="support_issue", importance="high",
        importance_reason="Donors who opted out are receiving mail they asked not to get.",
        captured_at="2026-09-11T10:02:14Z"),
    # Plainly the existing reporting theme.
    _claim(
        source="gong",
        source_ref=_gong_ref("7782934451119", "6390", "Serena Oyelowo", 336000),
        account_id="ACC-0006", account_name="Copper Ridge Youth Foundation",
        account_type="customer",
        verbatim="The membership export stops at ten thousand rows, so we run it four times and staple the files together.",
        paraphrase="Exports stop at ten thousand rows, so staff run the export repeatedly and merge the files.",
        topic="report export row cap", product_area="reporting",
        claim_type="support_issue", importance="high",
        importance_reason="A recurring manual workaround on every board report.",
        captured_at="2026-09-11T08:55:30Z"),
]

# --------------------------------------------------------------------------- the store

THEMES: list[dict[str, Any]] = [
    {
        "schema_version": "1.0.0",
        "theme_id": "THEME-0001",
        "title": "Report exports truncate above ten thousand rows",
        "aliases": ["export cap", "report truncation"],
        "product_area": "reporting",
        "status": "open",
        "owner": "ai-operations",
        "source": "synthesized",
        "last_verified": "2026-09-07",
        "run_id": PRIOR_RUN,
        "created_run": PRIOR_RUN,
        "last_updated_run": PRIOR_RUN,
        "accounts": ["ACC-0002"],
        "evidence": [PRIOR_CLAIMS[0]["claim_id"]],
        "score": 61,
        "score_inputs": {
            "distinct_customers": 1,
            "distinct_prospects": 0,
            "arr_sum": 268000,
            "open_cases": 2,
            "recency_days": 5,
            "claim_count": 1,
            "high_importance_count": 1,
        },
        "rationale": "An export that stops at ten thousand rows without saying so sends staff into board meetings with numbers they believe are complete.",
        "stale": False,
        "stale_reason": None,
        "last_evidence_at": "2026-09-02T15:04:11Z",
        "proposal_id": None,
        "filed_issue_url": None,
    },
    {
        "schema_version": "1.0.0",
        "theme_id": "THEME-0002",
        "title": "General ledger sync leaves journal entries unposted",
        "aliases": ["GL sync", "journal posting"],
        "product_area": "accounting",
        "status": "quiet",
        "owner": "ai-operations",
        "source": "synthesized",
        "last_verified": "2026-08-24",
        "run_id": QUIET_RUN,
        "created_run": QUIET_RUN,
        "last_updated_run": QUIET_RUN,
        "accounts": ["ACC-0005"],
        "evidence": [PRIOR_CLAIMS[1]["claim_id"]],
        "score": 34,
        "score_inputs": {
            "distinct_customers": 1,
            "distinct_prospects": 0,
            "arr_sum": 41000,
            "open_cases": 1,
            "recency_days": 21,
            "claim_count": 1,
            "high_importance_count": 0,
        },
        "rationale": "Journal entries that never reach the general ledger leave a month closed against books that do not balance.",
        "stale": True,
        "stale_reason": "no new evidence in more than fourteen days",
        "last_evidence_at": "2026-08-19T11:22:03Z",
        "proposal_id": None,
        "filed_issue_url": None,
    },
]


def _enrich(account_id: str, name: str, account_type: str, tier: str, arr: float,
            renewal: str | None, open_cases: int, case_ids: list[str],
            products: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "account_id": account_id,
        "account_name": name,
        "account_type": account_type,
        "tier": tier,
        "arr_usd": arr,
        "renewal_date": renewal,
        "open_case_count": open_cases,
        "open_case_ids": case_ids,
        "products": products,
    }


ENRICHMENT: dict[str, dict[str, Any]] = {
    record["account_id"]: record
    for record in [
        _enrich("ACC-0001", "Great Lakes Museum Alliance", "customer", "enterprise", 340000,
                "2026-11-30", 3, ["5008W00002aQpAaQAK", "5008W00002aQpAbQAK",
                                  "5008W00002aQpAcQAK"],
                ["membership", "events", "fundraising", "reporting"]),
        _enrich("ACC-0002", "Cascadia Nurses Association", "customer", "enterprise", 268000,
                "2027-02-28", 2, ["5008W00002aQpBaQAK", "5008W00002aQpBbQAK"],
                ["membership", "events", "lms", "reporting"]),
        _enrich("ACC-0003", "Prairie Land Trust Council", "customer", "professional", 154000,
                "2026-10-31", 2, ["5008W00002aQpLrQAK", "5008W00002aQpCbQAK"],
                ["membership", "fundraising", "accounting"]),
        _enrich("ACC-0004", "Atlantic Shipwrights Guild", "customer", "professional", 96000,
                "2027-01-31", 1, ["5008W00002aQpDaQAK"], ["membership", "events", "jobs"]),
        _enrich("ACC-0005", "Sunbelt Literacy Network", "customer", "standard", 41000,
                "2026-12-31", 1, ["5008W00002aQpKmQAK"], ["fundraising", "accounting"]),
        _enrich("ACC-0006", "Copper Ridge Youth Foundation", "customer", "standard", 18000,
                "2027-03-31", 1, ["5008W00002aQpEaQAK"], ["membership", "reporting"]),
        _enrich("ACC-0007", "Northwoods Arborists Society", "prospect", "prospect", 0,
                None, 0, [], ["lms"]),
    ]
}


def build_store(path: Any) -> Any:
    """Materialise the two existing themes into a store at `path` and return the Store."""
    from digest.store import Store, render_theme_body

    store = Store(path)
    by_id = {claim["claim_id"]: claim for claim in PRIOR_CLAIMS}
    for theme in THEMES:
        evidence = [by_id[cid] for cid in theme["evidence"] if cid in by_id]
        store.write_theme(theme, render_theme_body(theme, evidence))
    store.rebuild_index(RUN_ID)
    return store


def claims_by_topic() -> dict[str, str]:
    """Short names for the eight claims, so an assertion reads as prose."""
    return {
        "renewal_statement": RUN_CLAIMS[0]["claim_id"],
        "mid_year_upgrade": RUN_CLAIMS[1]["claim_id"],
        "event_checkin": RUN_CLAIMS[2]["claim_id"],
        "attendee_kiosk": RUN_CLAIMS[3]["claim_id"],
        "prospect_scorm": RUN_CLAIMS[4]["claim_id"],
        "pledge_frequency": RUN_CLAIMS[5]["claim_id"],
        "pledge_channel": RUN_CLAIMS[6]["claim_id"],
        "export_row_cap": RUN_CLAIMS[7]["claim_id"],
    }
