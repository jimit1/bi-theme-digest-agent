"""Tests for digest.verify: schema validation and citation verification.

Fixtures live in tests/fixtures/b10/. The Gong fixture mirrors
contracts/examples/SourceDocument.example.json plus one extra momentive-side turn, so
the pinned Claim.example.json test vector for claim_id can be checked against the same
turn shape a real connector produces.
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from digest.contracts import ContractViolation
from digest.errors import CitationUnresolved
from digest.verify import (
    citation_label,
    compute_claim_id,
    finalize_claim,
    resolve_citation,
    validate_reader_output,
    verify_citations,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "b10"
CONTRACTS = pathlib.Path(__file__).parent.parent / "contracts"

RUN_ID = "2026-09-08T06:00Z"
PROMPT_HASH = "80ab0b6e75c1789d"
MODEL_TIER = "extraction"

GONG_ACCOUNT = {
    "account_id": "ACC-0001",
    "account_name": "Great Lakes Museum Alliance",
    "account_type": "customer",
}
SFDC_ACCOUNT = {
    "account_id": "ACC-0003",
    "account_name": "Prairie Land Trust Council",
    "account_type": "customer",
}

FIRST_SENTENCE = (
    "Our renewal invoice came through with the full annual amount and there is no "
    "line anywhere showing the dues we already paid in March."
)
SECOND_SENTENCE = "We raised it in March and it has happened on every renewal since."


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _gong_source_doc() -> dict:
    return _load("source_gong.json")


def _sfdc_source_doc() -> dict:
    return _load("source_salesforce.json")


def _reader_claim(**overrides) -> dict:
    base = {
        "source": "gong",
        "source_ref": {
            "call_id": "7782934451002",
            "speaker_id": "4521",
            "start_ms": 418000,
            "end_ms": 437000,
        },
        "verbatim": FIRST_SENTENCE,
        "paraphrase": "Renewal invoices do not show the dues already paid earlier in the year.",
        "topic": "renewal invoice credit",
        "product_area": "membership",
        "claim_type": "support_issue",
        "importance": "high",
        "importance_reason": "Finance has to correct every renewal invoice by hand before it goes out.",
    }
    base.update(overrides)
    return base


def _reader_output(claims: list[dict], **overrides) -> dict:
    base = {
        "schema_version": "1.0.0",
        "source": "gong",
        "source_id": "7782934451002",
        "claims": claims,
        "no_claims_reason": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# validate_reader_output
# ---------------------------------------------------------------------------

def test_validate_reader_output_accepts_the_contract_example():
    raw = json.loads((CONTRACTS / "examples" / "ReaderOutput.example.json").read_text())
    result = validate_reader_output(raw)
    assert result is raw


def test_validate_reader_output_rejects_a_bad_document():
    with pytest.raises(ContractViolation):
        validate_reader_output({"not": "a reader output"})


# ---------------------------------------------------------------------------
# claim_id: the pinned test vector
# ---------------------------------------------------------------------------

def test_claim_id_matches_the_pinned_test_vector():
    example = json.loads((CONTRACTS / "examples" / "Claim.example.json").read_text())
    computed = compute_claim_id(example["source_ref"], example["verbatim"])
    assert computed == example["claim_id"]


def test_claim_id_stable_across_two_runs_of_the_same_input():
    source_doc = _gong_source_doc()
    claim_a = finalize_claim(_reader_claim(), source_doc, RUN_ID, GONG_ACCOUNT,
                              PROMPT_HASH, MODEL_TIER)
    claim_b = finalize_claim(_reader_claim(), source_doc, RUN_ID, GONG_ACCOUNT,
                              PROMPT_HASH, MODEL_TIER)
    assert claim_a["claim_id"] == claim_b["claim_id"]
    assert claim_a["claim_id"] == "e7e3c117f5c5"


def test_claim_id_changes_when_verbatim_changes():
    source_doc = _gong_source_doc()
    original = finalize_claim(_reader_claim(), source_doc, RUN_ID, GONG_ACCOUNT,
                               PROMPT_HASH, MODEL_TIER)
    changed = finalize_claim(
        _reader_claim(verbatim=FIRST_SENTENCE + " We raised it in March and it has "
                                "happened on every renewal since."),
        source_doc, RUN_ID, GONG_ACCOUNT, PROMPT_HASH, MODEL_TIER,
    )
    assert original["claim_id"] != changed["claim_id"]


# ---------------------------------------------------------------------------
# finalize_claim: field filling
# ---------------------------------------------------------------------------

def test_finalize_claim_fills_gong_source_ref_and_speaker_side():
    source_doc = _gong_source_doc()
    claim = finalize_claim(_reader_claim(), source_doc, RUN_ID, GONG_ACCOUNT,
                            PROMPT_HASH, MODEL_TIER)
    assert claim["source_ref"]["speaker_name"] == "Dana Ruiz"
    assert claim["source_ref"]["affiliation"] == "External"
    assert claim["speaker_side"] == "client"
    assert claim["account_id"] == "ACC-0001"
    assert claim["run_id"] == RUN_ID
    assert claim["prompt_hash"] == PROMPT_HASH
    assert claim["model_tier"] == MODEL_TIER


def test_finalize_claim_fills_salesforce_source_ref_and_speaker_side():
    source_doc = _sfdc_source_doc()
    reader_claim = _reader_claim(
        source="salesforce",
        source_ref={"case_id": "5008W00002aQpLrQAK", "comment_id": "00a8W00000XfT2mQAF"},
        verbatim="The GL sync drops the credit memo lines entirely",
        topic="GL sync",
        product_area="accounting",
        claim_type="support_issue",
    )
    claim = finalize_claim(reader_claim, source_doc, RUN_ID, SFDC_ACCOUNT,
                            PROMPT_HASH, MODEL_TIER)
    assert claim["source_ref"]["case_number"] == "00001042"
    assert claim["source_ref"]["author_id"] == "0058W00000abcDEQAY"
    assert claim["source_ref"]["author_name"] == "Jamie Cole"
    assert claim["source_ref"]["created_at"] == "2026-09-10T13:58:41Z"
    assert claim["speaker_side"] == "client"


def test_finalize_claim_never_mutates_the_reader_claim():
    reader_claim = _reader_claim()
    before = copy.deepcopy(reader_claim)
    finalize_claim(reader_claim, _gong_source_doc(), RUN_ID, GONG_ACCOUNT,
                    PROMPT_HASH, MODEL_TIER)
    assert reader_claim == before


def test_finalize_claim_raises_citation_unresolved_when_locator_does_not_resolve():
    reader_claim = _reader_claim(source_ref={
        "call_id": "7782934451002", "speaker_id": "9999", "start_ms": 0, "end_ms": 1000,
    })
    with pytest.raises(CitationUnresolved):
        finalize_claim(reader_claim, _gong_source_doc(), RUN_ID, GONG_ACCOUNT,
                        PROMPT_HASH, MODEL_TIER)


# ---------------------------------------------------------------------------
# verify_citations: one claim at a time, by reason code
# ---------------------------------------------------------------------------

def test_exact_match_accepted():
    output = _reader_output([_reader_claim()])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT,
                                           prompt_hash=PROMPT_HASH, model_tier=MODEL_TIER)
    assert rejected == []
    assert len(accepted) == 1
    assert accepted[0]["claim_id"] == "e7e3c117f5c5"
    assert accepted[0]["verbatim"] == FIRST_SENTENCE


def test_off_by_one_character_rejected():
    bad_verbatim = FIRST_SENTENCE[:-1] + "!"  # one character different from the source
    output = _reader_output([_reader_claim(verbatim=bad_verbatim)])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "citation_unresolved"


def test_span_covering_the_wrong_sentences_rejected():
    # The window covers only the second sentence, but the verbatim is the first
    # sentence's text. The turn itself resolves (speaker and call match, and the
    # window sits inside the turn's own extent); only the sentence selection is wrong.
    claim = _reader_claim(source_ref={
        "call_id": "7782934451002", "speaker_id": "4521",
        "start_ms": 430500, "end_ms": 437000,
    })
    output = _reader_output([claim])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "citation_unresolved"
    # Proves the fallback to the whole turn text never happens: the full turn text
    # does contain the first sentence, so a lenient check would have accepted this.
    full_turn_text = _gong_source_doc()["turns"][0]["text"]
    assert FIRST_SENTENCE in full_turn_text


def test_salesforce_comment_id_missing_rejected():
    claim = _reader_claim(
        source="salesforce",
        source_ref={"case_id": "5008W00002aQpLrQAK", "comment_id": "00a8W00000ZZZZmQAF"},
        verbatim="The GL sync drops the credit memo lines entirely",
    )
    output = _reader_output([claim], source="salesforce", source_id="5008W00002aQpLrQAK")
    accepted, rejected = verify_citations(output, _sfdc_source_doc(), RUN_ID, SFDC_ACCOUNT)
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "citation_unresolved"


def test_salesforce_exact_match_accepted():
    claim = _reader_claim(
        source="salesforce",
        source_ref={"case_id": "5008W00002aQpLrQAK", "comment_id": "00a8W00000XfT2mQAF"},
        verbatim="The GL sync drops the credit memo lines entirely",
        topic="GL sync",
        product_area="accounting",
    )
    output = _reader_output([claim], source="salesforce", source_id="5008W00002aQpLrQAK")
    accepted, rejected = verify_citations(output, _sfdc_source_doc(), RUN_ID, SFDC_ACCOUNT)
    assert rejected == []
    assert len(accepted) == 1
    assert accepted[0]["source_ref"]["case_number"] == "00001042"


def test_momentive_speaker_rejected():
    claim = _reader_claim(
        source_ref={"call_id": "7782934451002", "speaker_id": "1187",
                    "start_ms": 500000, "end_ms": 510000},
        verbatim="A lot of our customers ask for this exact same behavior.",
        topic="reporting exports",
        claim_type="feature_request",
    )
    output = _reader_output([claim])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "speaker_not_client"


def test_rejected_raw_carries_the_post_scrub_reader_claim():
    bad = _reader_claim(verbatim="not a real quote at all")
    output = _reader_output([bad])
    _accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert rejected[0]["raw"]["verbatim"] == "not a real quote at all"
    assert rejected[0]["raw"] == bad


def test_duplicate_claim_id_rejects_the_second():
    output = _reader_output([_reader_claim(), _reader_claim()])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "duplicate"


def test_schema_invalid_claim_rejected_without_blocking_siblings():
    malformed = _reader_claim(product_area="not_a_real_area")
    output = _reader_output([_reader_claim(), malformed])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "schema_invalid"


def test_verify_citations_never_mutates_the_reader_output():
    output = _reader_output([_reader_claim()])
    before = copy.deepcopy(output)
    verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    assert output == before


def test_full_reader_output_three_good_two_bad_yields_expected_split():
    good_one = _reader_claim()
    good_two = _reader_claim(source_ref={
        "call_id": "7782934451002", "speaker_id": "4521",
        "start_ms": 430500, "end_ms": 437000,
    }, verbatim=SECOND_SENTENCE, topic="renewal invoice follow up")
    good_three_claim = _reader_claim(
        source="salesforce",
        source_ref={"case_id": "5008W00002aQpLrQAK", "comment_id": "00a8W00000XfT2mQAF"},
        verbatim="The GL sync drops the credit memo lines entirely",
        topic="GL sync",
        product_area="accounting",
    )
    bad_speaker = _reader_claim(
        source_ref={"call_id": "7782934451002", "speaker_id": "1187",
                    "start_ms": 500000, "end_ms": 510000},
        verbatim="A lot of our customers ask for this exact same behavior.",
        topic="reporting exports",
        claim_type="feature_request",
    )
    bad_citation = _reader_claim(verbatim="this quote does not exist in the transcript")

    output = _reader_output([good_one, good_two, bad_speaker, bad_citation])
    accepted, rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    sfdc_output = _reader_output([good_three_claim], source="salesforce",
                                  source_id="5008W00002aQpLrQAK")
    sfdc_accepted, sfdc_rejected = verify_citations(sfdc_output, _sfdc_source_doc(), RUN_ID,
                                                     SFDC_ACCOUNT)

    all_accepted = accepted + sfdc_accepted
    all_rejected = rejected + sfdc_rejected
    assert len(all_accepted) == 3
    assert len(all_rejected) == 2
    reason_codes = sorted(r["reason_code"] for r in all_rejected)
    assert reason_codes == ["citation_unresolved", "speaker_not_client"]


# ---------------------------------------------------------------------------
# resolve_citation / citation_label
# ---------------------------------------------------------------------------

def test_resolve_citation_returns_the_resolved_span_text():
    output = _reader_output([_reader_claim()])
    accepted, _rejected = verify_citations(output, _gong_source_doc(), RUN_ID, GONG_ACCOUNT)
    resolved = resolve_citation(accepted[0], _gong_source_doc())
    assert resolved == FIRST_SENTENCE + " " + SECOND_SENTENCE


def test_citation_label_gong_formatting():
    claim = finalize_claim(_reader_claim(), _gong_source_doc(), RUN_ID, GONG_ACCOUNT,
                            PROMPT_HASH, MODEL_TIER)
    assert citation_label(claim) == "call 7782934451002 at 06:58"


def test_citation_label_salesforce_formatting():
    reader_claim = _reader_claim(
        source="salesforce",
        source_ref={"case_id": "5008W00002aQpLrQAK", "comment_id": "00a8W00000XfT2mQAF"},
        verbatim="The GL sync drops the credit memo lines entirely",
        topic="GL sync",
        product_area="accounting",
    )
    claim = finalize_claim(reader_claim, _sfdc_source_doc(), RUN_ID, SFDC_ACCOUNT,
                            PROMPT_HASH, MODEL_TIER)
    assert citation_label(claim) == "case 00001042 comment 00a8W00000XfT2mQAF"
