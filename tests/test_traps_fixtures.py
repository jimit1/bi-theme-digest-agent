"""The seven hand written trap fixtures, and the golden set that catches them.

A trap fixture is only worth having if the thing it plants is provably still there. These
tests do two jobs. First they assert the shape: every fixture validates against the schema
the contract names for it. Second, and more important, they assert the plant: the exact
sentence each trap exists to carry is present, in the file the golden set names, at the
location the golden set names, spoken by the side the golden set claims.

That is why the golden set and the fixtures were written in the same sitting. If somebody
edits a transcript and softens a sentence, this file fails rather than the eval quietly
passing on a trap that no longer traps anything.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from digest.contracts import validate  # noqa: E402

TRAPS = REPO / "data" / "mock" / "traps"
GOLDEN_PATH = REPO / "evals" / "golden_set.yaml"
SEED_EXAMPLE = REPO / "contracts" / "examples" / "CorpusSeedSpec.example.json"

T1A_CALL = "7782934451002"
T1B_CASE = "5008W00002aQpLrQAK"
T2A_CALL = "7782934451118"
T2B_CALL = "7782934451207"
T3_CALL = "7782934451311"
T4B_CALL = "7782934451404"
T4C_CALL = "7782934451119"

GONG_TRAPS = [T1A_CALL, T2A_CALL, T2B_CALL, T3_CALL, T4B_CALL, T4C_CALL]

PLANTED_PII = [
    "dana.whitfield@example.net",
    "(612) 555-0147",
    "4821 Larkspur Lane, Duluth, MN 55803",
    "Harold Pemberton-Vance",
]

# Enough to drop the grammar shared by any two English sentences. It only has to cover the
# words that would otherwise appear in both T1 sentences; every content word is left in.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "so", "that", "this", "these", "those", "it",
    "its", "is", "are", "was", "were", "be", "been", "of", "in", "on", "to", "for", "from",
    "with", "at", "by", "as", "we", "our", "us", "they", "them", "their", "i", "my", "you",
    "your", "not", "there", "then", "than", "if", "up", "do", "does", "did", "have", "has",
    "had", "will", "would", "can", "could", "should", "may", "might", "must", "who", "which",
    "when", "where", "how", "why", "all", "any", "one", "two",
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9.'-]*", text.lower())
    return {w.strip(".'-") for w in words if w.strip(".'-") and w not in STOPWORDS}


@pytest.fixture(scope="module")
def golden() -> dict:
    return yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def calls() -> dict:
    return {
        cid: json.loads((TRAPS / "gong" / "calls" / f"{cid}.json").read_text(encoding="utf-8"))
        for cid in GONG_TRAPS
    }


@pytest.fixture(scope="module")
def case() -> dict:
    path = TRAPS / "salesforce" / "cases" / f"{T1B_CASE}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def users() -> dict:
    return json.loads((TRAPS / "users.json").read_text(encoding="utf-8"))


def sentence_at(call: dict, speaker_id: str, start_ms: int) -> str:
    for block in call["transcript"]["transcript"]:
        if block["speakerId"] != speaker_id:
            continue
        for sentence in block["sentences"]:
            if sentence["start"] == start_ms:
                return sentence["text"]
    raise AssertionError(f"no sentence for speaker {speaker_id} at {start_ms}")


def affiliation_of(call: dict, speaker_id: str) -> str:
    for party in call["call"]["parties"]:
        if party["speakerId"] == speaker_id:
            return party["affiliation"]
    raise AssertionError(f"no party with speakerId {speaker_id}")


def comment_by_id(case_doc: dict, comment_id: str) -> dict:
    for comment in case_doc["comments"]:
        if comment["Id"] == comment_id:
            return comment
    raise AssertionError(f"no comment {comment_id}")


# --------------------------------------------------------------------------- shape

@pytest.mark.parametrize("call_id", GONG_TRAPS)
def test_gong_trap_validates(calls, call_id):
    validate(calls[call_id], "GongCallFile")


def test_salesforce_trap_validates(case):
    validate(case, "SalesforceCaseFile")


def test_trap_users_validate(users):
    validate(users, "SalesforceQueryResponse")


def test_trap_files_are_the_seven_the_contract_names():
    found = sorted(p.relative_to(TRAPS).as_posix() for p in TRAPS.rglob("*.json"))
    expected = sorted(
        [f"gong/calls/{cid}.json" for cid in GONG_TRAPS]
        + [f"salesforce/cases/{T1B_CASE}.json", "users.json"]
    )
    assert found == expected


def test_no_dashes_and_plain_ascii():
    for path in sorted(TRAPS.rglob("*.json")) + [GOLDEN_PATH]:
        raw = path.read_text(encoding="utf-8")
        assert "—" not in raw, f"em dash in {path}"
        assert "–" not in raw, f"en dash in {path}"
        raw.encode("ascii")


@pytest.mark.parametrize("call_id", GONG_TRAPS)
def test_transcripts_are_realistic_length(calls, call_id):
    call = calls[call_id]
    blocks = call["transcript"]["transcript"]
    assert len(blocks) >= 25, f"{call_id} has only {len(blocks)} monologues"
    duration = call["call"]["metaData"]["duration"]
    assert 1500 <= duration <= 2400, f"{call_id} duration {duration} is not 25 to 40 minutes"
    last_end = blocks[-1]["sentences"][-1]["end"]
    assert last_end <= duration * 1000


@pytest.mark.parametrize("call_id", GONG_TRAPS)
def test_planted_sentence_is_never_near_the_top(calls, golden, call_id):
    """A claim in the first minute would be found by luck rather than by reading."""
    call = calls[call_id]
    starts = [
        entry["start_ms"] for entry in golden["must_appear"]
        if entry.get("source_id") == call_id
    ] + [
        entry["start_ms"] for entry in golden["must_not_appear"]
        if entry.get("source_id") == call_id
    ]
    for start_ms in starts:
        assert start_ms > 120000, f"{call_id} plants at {start_ms} ms, too near the top"


def test_trap_users_cover_the_four_staff_and_the_client_contact(users):
    by_name = {r["Name"]: r for r in users["records"]}
    staff = ["Priya Natarajan", "Marcus Oyelaran", "Elena Kowalczyk", "Tom Bradshaw"]
    for name in staff:
        assert by_name[name]["UserType"] == "Standard", name
    client = [r for r in users["records"] if r["UserType"] != "Standard"]
    assert len(client) == 1
    assert client[0]["UserType"] in {"CspLitePortal", "PowerCustomerSuccess"}
    for record in users["records"]:
        assert record["Id"].startswith("005"), record["Id"]
        assert len(record["Id"]) == 18, record["Id"]


def test_comment_authors_resolve_to_a_trap_user(case, users):
    known = {r["Id"] for r in users["records"]}
    for comment in case["comments"]:
        assert comment["CreatedById"] in known, comment["CreatedById"]


def test_external_party_domains_match_the_pinned_account(calls, golden):
    """The connector resolves a Gong account from the party email domain, so the domain in
    the fixture has to be the one the seed spec pins for the account the golden set expects."""
    seed = json.loads(SEED_EXAMPLE.read_text(encoding="utf-8"))
    domains = {a["account_id"]: a["domain"] for a in seed["accounts"]}
    expected = {e["source_id"]: e["expected_account_id"]
                for e in golden["must_appear"] if e["source"] == "gong"}
    expected[T4C_CALL] = "ACC-0006"
    expected[T4B_CALL] = "ACC-0005"
    for call_id, account_id in expected.items():
        externals = [p for p in calls[call_id]["call"]["parties"]
                     if p["affiliation"] == "External"]
        assert externals, call_id
        for party in externals:
            assert party["emailAddress"].split("@")[1] == domains[account_id], call_id


# --------------------------------------------------------------------------- T1

def test_t1_pair_shares_no_keyword_beyond_invoice(calls, case, golden):
    entries = {e["id"]: e for e in golden["must_appear"]}
    a = sentence_at(calls[T1A_CALL], entries["T1a"]["speaker_id"], entries["T1a"]["start_ms"])
    body = comment_by_id(case, entries["T1b"]["comment_id"])["CommentBody"]
    b = next(s for s in re.split(r"(?<=\.)\s+", body)
             if entries["T1b"]["expected_verbatim_substring"] in s)
    overlap = tokenize(a) & tokenize(b)
    assert overlap <= {"invoice", "invoices"}, sorted(overlap)


def test_t1_pair_never_shares_the_banned_vocabulary(calls, case, golden):
    entries = {e["id"]: e for e in golden["must_appear"]}
    a = sentence_at(calls[T1A_CALL], entries["T1a"]["speaker_id"], entries["T1a"]["start_ms"])
    b = comment_by_id(case, entries["T1b"]["comment_id"])["CommentBody"]
    for word in ("credit", "proration", "dues"):
        assert not (word in a.lower() and word in b.lower()), word


# --------------------------------------------------------------------------- T2

def test_t2a_says_event_checkin_twice_and_never_kiosk(calls):
    raw = json.dumps(calls[T2A_CALL], ensure_ascii=False)
    assert raw.count("event check-in") >= 2
    assert "kiosk" not in raw.lower()


def test_t2b_says_the_attendee_kiosk_twice_and_never_checkin(calls):
    raw = json.dumps(calls[T2B_CALL], ensure_ascii=False)
    assert raw.count("the attendee kiosk") >= 2
    assert "check-in" not in raw.lower()


@pytest.mark.parametrize("call_id,phrase", [(T2A_CALL, "event check-in"),
                                            (T2B_CALL, "the attendee kiosk")])
def test_t2_names_are_spoken_by_the_client_not_by_us(calls, call_id, phrase):
    call = calls[call_id]
    for block in call["transcript"]["transcript"]:
        for sentence in block["sentences"]:
            if phrase in sentence["text"]:
                assert affiliation_of(call, block["speakerId"]) == "External"


# --------------------------------------------------------------------------- T4

def test_t4a_churn_comment_is_unpublished(case, golden):
    entry = next(e for e in golden["must_not_appear"] if e["id"] == "T4a")
    comment = comment_by_id(case, entry["comment_id"])
    assert comment["IsPublished"] is False
    assert entry["forbidden_substring"] in comment["CommentBody"]


def test_t4a_is_the_only_unpublished_comment(case):
    assert sum(1 for c in case["comments"] if not c["IsPublished"]) == 1


def test_t4b_planted_pii_is_present_in_the_call(calls):
    """The scrubber has to have something to remove. Note the contract puts the PII in the
    T4b call, 7782934451404, not in the T1 call."""
    raw = json.dumps(calls[T4B_CALL], ensure_ascii=False)
    for value in PLANTED_PII:
        assert value in raw, value


def test_t4b_pii_sits_in_one_external_turn(calls):
    call = calls[T4B_CALL]
    hits = [
        (block["speakerId"], sentence["text"])
        for block in call["transcript"]["transcript"]
        for sentence in block["sentences"]
        if any(value in sentence["text"] for value in PLANTED_PII)
    ]
    assert len(hits) == 1
    speaker_id, text = hits[0]
    assert affiliation_of(call, speaker_id) == "External"
    for value in PLANTED_PII:
        assert value in text


def test_t4c_sentence_is_spoken_by_an_internal_speaker(calls, golden):
    entry = next(e for e in golden["must_not_appear"] if e["id"] == "T4c")
    call = calls[T4C_CALL]
    text = sentence_at(call, entry["speaker_id"], entry["start_ms"])
    assert entry["forbidden_substring"] in text
    assert affiliation_of(call, entry["speaker_id"]) == "Internal"


# --------------------------------------------------------------------------- golden set

def test_golden_must_appear_resolves_in_the_fixtures(calls, case, users, golden):
    entries = golden["must_appear"]
    assert [e["id"] for e in entries] == ["T1a", "T1b", "T2a", "T2b", "T3"]
    staff_ids = {r["Id"] for r in users["records"] if r["UserType"] == "Standard"}
    for entry in entries:
        substring = entry["expected_verbatim_substring"]
        assert 6 <= len(substring.split()) <= 12, entry["id"]
        assert entry["expected_speaker_side"] == "client"
        if entry["source"] == "gong":
            call = calls[entry["source_id"]]
            text = sentence_at(call, entry["speaker_id"], entry["start_ms"])
            assert substring in text, entry["id"]
            assert affiliation_of(call, entry["speaker_id"]) == "External", entry["id"]
        else:
            comment = comment_by_id(case, entry["comment_id"])
            assert substring in comment["CommentBody"], entry["id"]
            assert comment["IsPublished"] is True, entry["id"]
            assert comment["CreatedById"] not in staff_ids, entry["id"]


def test_golden_must_not_appear_is_actually_planted(calls, case, golden):
    entries = golden["must_not_appear"]
    assert [e["id"] for e in entries] == ["T4a", "T4c"]
    for entry in entries:
        if entry["source"] == "gong":
            text = sentence_at(calls[entry["source_id"]], entry["speaker_id"],
                               entry["start_ms"])
            assert entry["forbidden_substring"] in text, entry["id"]
        else:
            comment = comment_by_id(case, entry["comment_id"])
            assert entry["forbidden_substring"] in comment["CommentBody"], entry["id"]


def test_golden_pii_list_is_the_four_planted_values(golden):
    assert [e["value"] for e in golden["pii_must_not_appear"]] == PLANTED_PII
    assert [e["kind"] for e in golden["pii_must_not_appear"]] == [
        "email", "phone", "address", "name"]


def test_golden_structural_checks_are_the_seven_from_the_spec(golden):
    names = [entry["check"]["name"] for entry in golden["structural"]]
    assert names == [
        "every_claim_cited_and_resolves",
        "t1_single_theme",
        "t2_aliases_both_names",
        "t3_prospect_ranks_below_customers",
        "no_pii_in_store",
        "rerun_same_theme_ids",
        "stale_flag_fires_w39",
    ]
    by_name = {entry["check"]["name"]: entry for entry in golden["structural"]}
    assert by_name["t1_single_theme"]["check"]["source_ids"] == [T1A_CALL, T1B_CASE]
    assert by_name["t2_aliases_both_names"]["check"]["names"] == [
        "event check-in", "attendee kiosk"]
    assert by_name["no_pii_in_store"]["check"]["values"] == PLANTED_PII
    for entry in golden["structural"]:
        assert entry["id"] and entry["description"]


def test_golden_stability_block(golden):
    assert golden["stability"] == {
        "metric": "jaccard_claim_to_theme",
        "expect": 1.0,
        "report_if_lower": True,
    }
