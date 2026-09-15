"""Tests for `digest.enrich` and `digest.score`.

Three themes are scored by hand against the formula in `contracts/INTERFACES.md` and the
result is asserted against the number computed here, not against the code under test, so a
bug in `digest.score` cannot hide behind a bug in this file agreeing with it:

- `test_score_customer_heavy_theme`: two customers, ARR at the 500000 cap, open cases over
  the cap of 4, two high importance claims, evidence landed today. Expected score 82.
- `test_score_prospect_only_theme`: one prospect, no customer evidence at all, which
  triggers the 0.5 multiplier. Expected score 8.
- `test_score_quiet_old_theme`: one customer, evidence more than 14 days old, so the recency
  term floors at zero. Expected score 13.

A fourth case, `test_score_rounding_floor_half_up`, is not one of the three: it exists only
to pin `floor(total + 0.5)` at an exact `.5` boundary (37.5 -> 38), because that is the one
place `round()` and this rule can silently disagree.

`digest.enrich` is tested against a fake connector that answers `sfdc_get_accounts` and
`sfdc_query_cases` the way `digest.connectors.mcp_client.McpToolClient` does: `.call(tool,
arguments, schema=schema_name)` returning a validated document, plus a `.window` property.
"""
from __future__ import annotations

import datetime as _dt
import os
import pathlib

import pytest

from digest.contracts import validate
from digest.enrich import enrich
from digest.score import explain, rank, score

FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "b11"
AS_OF = _dt.date(2026, 9, 14)


# ---------------------------------------------------------------------------
# Small builders. Every document built here is validated against its contract before use,
# so a typo in a fixture fails loudly in this file rather than silently in the code under
# test.
# ---------------------------------------------------------------------------

def _enrichment(account_id: str, *, account_type: str, tier: str, arr_usd: float,
                renewal_date: str | None, open_case_ids: list[str],
                products: list[str]) -> dict:
    doc = {
        "schema_version": "1.0.0",
        "account_id": account_id,
        "account_name": account_id + " Inc",
        "account_type": account_type,
        "tier": tier,
        "arr_usd": arr_usd,
        "renewal_date": renewal_date,
        "open_case_count": len(open_case_ids),
        "open_case_ids": open_case_ids,
        "products": products,
    }
    validate(doc, "Enrichment")
    return doc


def _sfdc_claim(claim_id: str, *, account_id: str, account_type: str, importance: str,
                 created_at: str) -> dict:
    doc = {
        "schema_version": "1.0.0",
        "claim_id": claim_id,
        "run_id": "2026-09-14T07:00Z",
        "source": "salesforce",
        "source_ref": {
            "case_id": "CASE0000000000%03d" % 1,
            "case_number": "00001042",
            "comment_id": "CMNT0000000000%03d" % 1,
            "author_id": "USER0000000000001",
            "author_name": "A Customer",
            "created_at": created_at,
        },
        "account_id": account_id,
        "account_name": account_id + " Inc",
        "account_type": account_type,
        "speaker_side": "client",
        "verbatim": "This is exactly the substring we cited.",
        "paraphrase": "One plain sentence about the problem.",
        "topic": "renewal invoice credit",
        "product_area": "membership",
        "claim_type": "support_issue",
        "importance": importance,
        "importance_reason": "It blocks the renewal from closing.",
        "captured_at": "2026-09-14T06:05:00Z",
        "prompt_hash": "%016x" % (int(claim_id, 16) + 1),
        "model_tier": "extraction",
    }
    validate(doc, "Claim")
    return doc


def _gong_claim(claim_id: str, *, account_id: str, account_type: str, importance: str,
                 captured_at: str) -> dict:
    doc = {
        "schema_version": "1.0.0",
        "claim_id": claim_id,
        "run_id": "2026-09-14T07:00Z",
        "source": "gong",
        "source_ref": {
            "call_id": "7782934451002",
            "speaker_id": "4521",
            "speaker_name": "Dana Ruiz",
            "affiliation": "External",
            "start_ms": 418000,
            "end_ms": 437000,
        },
        "account_id": account_id,
        "account_name": account_id + " Inc",
        "account_type": account_type,
        "speaker_side": "client",
        "verbatim": "This is exactly the substring we cited on the call.",
        "paraphrase": "One plain sentence about the problem.",
        "topic": "renewal invoice credit",
        "product_area": "membership",
        "claim_type": "support_issue",
        "importance": importance,
        "importance_reason": "It blocks the renewal from closing.",
        "captured_at": captured_at,
        "prompt_hash": "%016x" % (int(claim_id, 16) + 2),
        "model_tier": "extraction",
    }
    validate(doc, "Claim")
    return doc


# ---------------------------------------------------------------------------
# score(): three hand-computed themes
# ---------------------------------------------------------------------------

def test_score_customer_heavy_theme():
    # customers = 30 * min(2, 4) / 4               = 15
    # value     = 25 * min(500000, 500000) / 500000 = 25
    # cases     = 20 * min(5, 4) / 4                = 20      (5 open cases, capped at 4)
    # recency   = 15 * max(0, 14 - 0) / 14           = 15      (newest claim is today)
    # severity  = 10 * min(2, 3) / 3                 = 6.666666666666667
    # total     = 15 + 25 + 20 + 15 + 6.666666666666667 = 81.66666666666667
    # score     = floor(81.66666666666667 + 0.5) = floor(82.16666666666667) = 82
    enrichment_by_account = {
        "ACC-0001": _enrichment(
            "ACC-0001", account_type="customer", tier="enterprise", arr_usd=200000,
            renewal_date="2026-12-31", open_case_ids=["CASE00000000000001", "CASE00000000000002"],
            products=["membership", "events"],
        ),
        "ACC-0002": _enrichment(
            "ACC-0002", account_type="customer", tier="enterprise", arr_usd=300000,
            renewal_date="2027-03-31",
            open_case_ids=["CASE00000000000003", "CASE00000000000004", "CASE00000000000005"],
            products=["fundraising"],
        ),
    }
    claims = [
        _sfdc_claim("000000000001", account_id="ACC-0001", account_type="customer",
                    importance="high", created_at="2026-09-14T09:00:00Z"),
        _sfdc_claim("000000000002", account_id="ACC-0001", account_type="customer",
                    importance="medium", created_at="2026-09-01T09:00:00Z"),
        _gong_claim("000000000003", account_id="ACC-0002", account_type="customer",
                    importance="high", captured_at="2026-09-05T08:00:00Z"),
    ]
    claims_by_id = {c["claim_id"]: c for c in claims}
    theme = {"theme_id": "THEME-1001", "evidence": [c["claim_id"] for c in claims]}

    result_score, inputs = score(theme, enrichment_by_account, claims_by_id, AS_OF)

    assert inputs == {
        "distinct_customers": 2,
        "distinct_prospects": 0,
        "arr_sum": 500000.0,
        "open_cases": 5,
        "recency_days": 0,
        "claim_count": 3,
        "high_importance_count": 2,
    }
    assert result_score == 82


def test_score_prospect_only_theme():
    # customers = 0, value = 0, cases = 0 (no customer accounts at all)
    # recency   = 15 * max(0, 14 - 3) / 14 = 11.785714285714286
    # severity  = 10 * min(1, 3) / 3        = 3.3333333333333335
    # total     = 15.11904761904762, halved to 7.55952380952381 (prospect only)
    # score     = floor(7.55952380952381 + 0.5) = floor(8.05952380952381) = 8
    enrichment_by_account = {
        "ACC-0003": _enrichment(
            "ACC-0003", account_type="prospect", tier="prospect", arr_usd=0,
            renewal_date=None, open_case_ids=[], products=[],
        ),
    }
    claims = [
        _sfdc_claim("000000000004", account_id="ACC-0003", account_type="prospect",
                    importance="high", created_at="2026-09-11T09:00:00Z"),
        _sfdc_claim("000000000005", account_id="ACC-0003", account_type="prospect",
                    importance="low", created_at="2026-09-01T09:00:00Z"),
    ]
    claims_by_id = {c["claim_id"]: c for c in claims}
    theme = {"theme_id": "THEME-1002", "evidence": [c["claim_id"] for c in claims]}

    result_score, inputs = score(theme, enrichment_by_account, claims_by_id, AS_OF)

    assert inputs["distinct_customers"] == 0
    assert inputs["distinct_prospects"] == 1
    assert inputs["arr_sum"] == 0.0
    assert inputs["open_cases"] == 0
    assert inputs["recency_days"] == 3
    assert inputs["claim_count"] == 2
    assert inputs["high_importance_count"] == 1
    assert result_score == 8

    explanation = explain(theme, inputs)
    assert "prospect only" in explanation
    assert "* 0.5" in explanation


def test_score_quiet_old_theme():
    # customers = 30 * min(1, 4) / 4 = 7.5
    # value     = 25 * min(100000, 500000) / 500000 = 5.0
    # cases     = 0 (no open cases)
    # recency   = 15 * max(0, 14 - recency_days) / 14 = 0 (evidence is over 14 days old)
    # severity  = 0 (no high importance evidence)
    # total     = 7.5 + 5.0 = 12.5
    # score     = floor(12.5 + 0.5) = floor(13.0) = 13
    enrichment_by_account = {
        "ACC-0004": _enrichment(
            "ACC-0004", account_type="customer", tier="professional", arr_usd=100000,
            renewal_date="2026-11-30", open_case_ids=[], products=["fundraising", "accounting"],
        ),
    }
    claims = [
        _sfdc_claim("000000000006", account_id="ACC-0004", account_type="customer",
                    importance="low", created_at="2026-08-01T09:00:00Z"),
    ]
    claims_by_id = {c["claim_id"]: c for c in claims}
    theme = {"theme_id": "THEME-1003", "evidence": [c["claim_id"] for c in claims]}

    result_score, inputs = score(theme, enrichment_by_account, claims_by_id, AS_OF)

    assert inputs["recency_days"] > 14
    assert inputs["distinct_customers"] == 1
    assert inputs["arr_sum"] == 100000.0
    assert inputs["open_cases"] == 0
    assert inputs["high_importance_count"] == 0
    assert result_score == 13


def test_score_rounding_floor_half_up():
    # Pins floor(total + 0.5) at an exact .5 boundary, the one place round() could differ.
    # customers = 30 * min(3, 4) / 4 = 22.5, value = 0, cases = 0, severity = 0,
    # recency = 15 * max(0, 14 - 0) / 14 = 15.0, total = 37.5, floor(37.5 + 0.5) = 38.
    enrichment_by_account = {
        acc_id: _enrichment(acc_id, account_type="customer", tier="standard", arr_usd=0,
                            renewal_date="2026-10-15", open_case_ids=[], products=[])
        for acc_id in ("ACC-0005", "ACC-0006", "ACC-0007")
    }
    claims = [
        _sfdc_claim("00000000000%d" % i, account_id=acc_id, account_type="customer",
                    importance="low", created_at="2026-09-14T09:00:00Z")
        for i, acc_id in enumerate(("ACC-0005", "ACC-0006", "ACC-0007"), start=7)
    ]
    claims_by_id = {c["claim_id"]: c for c in claims}
    theme = {"theme_id": "THEME-1004", "evidence": [c["claim_id"] for c in claims]}

    result_score, inputs = score(theme, enrichment_by_account, claims_by_id, AS_OF)

    assert inputs["distinct_customers"] == 3
    assert inputs["recency_days"] == 0
    assert result_score == 38


def test_explain_contains_every_input_and_the_total():
    enrichment_by_account = {
        "ACC-0001": _enrichment(
            "ACC-0001", account_type="customer", tier="enterprise", arr_usd=200000,
            renewal_date="2026-12-31", open_case_ids=["CASE00000000000001"],
            products=["membership"],
        ),
    }
    claims = [
        _sfdc_claim("00000000000a", account_id="ACC-0001", account_type="customer",
                    importance="high", created_at="2026-09-14T09:00:00Z"),
    ]
    claims_by_id = {c["claim_id"]: c for c in claims}
    theme = {"theme_id": "THEME-1005", "evidence": [c["claim_id"] for c in claims]}

    result_score, inputs = score(theme, enrichment_by_account, claims_by_id, AS_OF)
    explanation = explain(theme, inputs)

    for key in ("distinct_customers", "distinct_prospects", "open_cases", "recency_days",
                "claim_count", "high_importance_count"):
        assert str(inputs[key]) in explanation, "missing %s in explain output" % key
    assert ("%.2f" % inputs["arr_sum"]) in explanation
    assert str(result_score) in explanation
    assert theme["theme_id"] in explanation


# ---------------------------------------------------------------------------
# rank(): tie-breaks
# ---------------------------------------------------------------------------

def test_rank_tie_breaks():
    themes = [
        {"theme_id": "THEME-0002", "score": 90, "score_inputs": {"distinct_customers": 2}},
        {"theme_id": "THEME-0001", "score": 90, "score_inputs": {"distinct_customers": 3}},
        {"theme_id": "THEME-0005", "score": 90, "score_inputs": {"distinct_customers": 3}},
        {"theme_id": "THEME-0009", "score": 70, "score_inputs": {"distinct_customers": 10}},
    ]

    ordered = [t["theme_id"] for t in rank(themes)]

    assert ordered == ["THEME-0001", "THEME-0005", "THEME-0002", "THEME-0009"]


# ---------------------------------------------------------------------------
# enrich(): a fake connector standing in for McpToolClient.call() / .window
# ---------------------------------------------------------------------------

class _FakeSfdcConnector:
    """Answers `sfdc_get_accounts` and `sfdc_query_cases` the way `McpToolClient.call` does:
    JSON in, a validated `SalesforceQueryResponse` document out."""

    window = {"from": "2026-09-01T00:00:00Z", "to": "2026-09-14T23:59:59Z"}

    _ACCOUNTS_BY_ID = {
        "SFDC00000000000001": {"Id": "SFDC00000000000001", "Name": "Great Lakes Museum Alliance",
                               "Tier__c": "Enterprise", "ARR__c": 200000,
                               "Renewal_Date__c": "2026-12-31", "Products__c": "membership;events"},
        "SFDC00000000000002": {"Id": "SFDC00000000000002", "Name": "Cascadia Nurses Association",
                               "Tier__c": "Enterprise", "ARR__c": 300000,
                               "Renewal_Date__c": "2027-03-31", "Products__c": "fundraising"},
        "SFDC00000000000003": {"Id": "SFDC00000000000003", "Name": "Northwoods Arborists Society",
                               "Tier__c": "Prospect", "ARR__c": 0,
                               "Renewal_Date__c": None, "Products__c": ""},
        "SFDC00000000000004": {"Id": "SFDC00000000000004", "Name": "Prairie Land Trust Council",
                               "Tier__c": "Professional", "ARR__c": 100000,
                               "Renewal_Date__c": "2026-11-30", "Products__c": "fundraising;accounting"},
    }

    _CASES = [
        {"Id": "CASE00000000000001", "CaseNumber": "00000001", "AccountId": "SFDC00000000000001",
         "Subject": "s", "Status": "Working", "Priority": "High",
         "CreatedDate": "2026-09-10T10:00:00Z", "ClosedDate": None},
        {"Id": "CASE00000000000002", "CaseNumber": "00000002", "AccountId": "SFDC00000000000001",
         "Subject": "s", "Status": "New", "Priority": "Medium",
         "CreatedDate": "2026-09-11T10:00:00Z", "ClosedDate": None},
        {"Id": "CASE00000000000003", "CaseNumber": "00000003", "AccountId": "SFDC00000000000001",
         "Subject": "s", "Status": "Closed", "Priority": "Low",
         "CreatedDate": "2026-09-02T10:00:00Z", "ClosedDate": "2026-09-05T10:00:00Z"},
        {"Id": "CASE00000000000004", "CaseNumber": "00000004", "AccountId": "SFDC00000000000002",
         "Subject": "s", "Status": "Escalated", "Priority": "High",
         "CreatedDate": "2026-09-12T10:00:00Z", "ClosedDate": None},
        {"Id": "CASE00000000000005", "CaseNumber": "00000005", "AccountId": "SFDC00000000000004",
         "Subject": "s", "Status": "Closed", "Priority": "Low",
         "CreatedDate": "2026-09-03T10:00:00Z", "ClosedDate": "2026-09-06T10:00:00Z"},
    ]

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool, arguments, schema=None):
        self.calls.append((tool, dict(arguments)))
        if tool == "sfdc_get_accounts":
            wanted = arguments["account_ids"]
            records = [
                dict(self._ACCOUNTS_BY_ID[i], attributes={"type": "Account", "url": "/x"})
                for i in wanted if i in self._ACCOUNTS_BY_ID
            ]
            document = self._envelope(records, "Account")
        elif tool == "sfdc_query_cases":
            records = [dict(c, attributes={"type": "Case", "url": "/x"}) for c in self._CASES]
            document = self._envelope(records, "Case")
        else:
            raise AssertionError("unexpected tool %r" % tool)
        if schema is not None:
            validate(document, schema)
        return document

    @staticmethod
    def _envelope(records, record_type):
        fields = list(records[0].keys()) if records else ["Id"]
        fields = [f for f in fields if f != "attributes"]
        return {
            "schema_version": "1.0.0",
            "totalSize": len(records),
            "done": True,
            "records": records,
            "meta": {
                "window": {"from": "2026-09-01T00:00:00Z", "to": "2026-09-14T23:59:59Z"},
                "rows_returned": len(records),
                "row_cap": 200,
                "withheld_comment_count": 0,
                "fields_allowlisted": fields,
                "soql": "SELECT %s FROM %s" % (", ".join(fields), record_type),
            },
        }


@pytest.fixture(autouse=True)
def _mock_dir(monkeypatch):
    monkeypatch.setenv("DIGEST_MOCK_DIR", str(FIXTURES_DIR))


def test_enrich_customer_accounts():
    connector = _FakeSfdcConnector()

    result = enrich(["ACC-0001", "ACC-0002"], connector)

    assert set(result) == {"ACC-0001", "ACC-0002"}
    acc1 = result["ACC-0001"]
    assert acc1["account_type"] == "customer"
    assert acc1["tier"] == "enterprise"
    assert acc1["arr_usd"] == 200000.0
    assert acc1["renewal_date"] == "2026-12-31"
    assert acc1["products"] == ["membership", "events"]
    # Two open cases (Working, New) and one Closed case excluded.
    assert acc1["open_case_count"] == 2
    assert acc1["open_case_ids"] == ["CASE00000000000001", "CASE00000000000002"]

    acc2 = result["ACC-0002"]
    assert acc2["open_case_count"] == 1
    assert acc2["open_case_ids"] == ["CASE00000000000004"]

    for doc in result.values():
        validate(doc, "Enrichment")

    tool_names = [name for name, _ in connector.calls]
    assert tool_names.count("sfdc_get_accounts") == 1
    assert tool_names.count("sfdc_query_cases") == 1


def test_enrich_prospect_has_zero_arr_and_null_renewal():
    connector = _FakeSfdcConnector()

    result = enrich(["ACC-0003"], connector)

    prospect = result["ACC-0003"]
    assert prospect["account_type"] == "prospect"
    assert prospect["tier"] == "prospect"
    assert prospect["arr_usd"] == 0.0
    assert prospect["renewal_date"] is None
    assert prospect["products"] == []
    assert prospect["open_case_count"] == 0


def test_enrich_account_with_only_closed_cases_has_zero_open_count():
    connector = _FakeSfdcConnector()

    result = enrich(["ACC-0004"], connector)

    assert result["ACC-0004"]["open_case_count"] == 0
    assert result["ACC-0004"]["open_case_ids"] == []


def test_enrich_unknown_account_raises_key_error():
    connector = _FakeSfdcConnector()

    with pytest.raises(KeyError):
        enrich(["ACC-9999"], connector)


def test_enrich_empty_account_list_returns_empty_dict():
    connector = _FakeSfdcConnector()

    assert enrich([], connector) == {}
    assert connector.calls == []
