"""Tests for tools/generate_corpus.py and the non trap mock corpus it commits.

Per build/briefs/B2.md requirement 19: regenerate into a temp dir and assert byte identical
to the committed output; assert counts per week; assert every file validates against its
contract schema; assert no [EMAIL]-shaped or @ containing text in any transcript sentence or
comment body; assert no U+2013/U+2014 anywhere in data/mock/gong, data/mock/salesforce.

This file owns nothing outside itself: it never writes into data/mock, it only reads the
committed corpus and a scratch temp directory.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
TOOLS = REPO / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from digest.contracts import validate  # noqa: E402

import generate_corpus as gc  # noqa: E402

MOCK_DIR = REPO / "data" / "mock"
SPEC_PATH = MOCK_DIR / "seed_spec.yaml"

EM_DASH = "—"
EN_DASH = "–"


@pytest.fixture(scope="module")
def spec() -> dict:
    return gc.load_spec(SPEC_PATH)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory, spec) -> Path:
    out_dir = tmp_path_factory.mktemp("corpus_regen")
    outputs = gc.generate(spec)
    gc.write_outputs(outputs, out_dir)
    return out_dir


def _relative_json_files(root: Path) -> list[Path]:
    return sorted(
        p.relative_to(root)
        for p in list(root.glob("gong/calls/*.json"))
        + list(root.glob("salesforce/cases/*.json"))
        + [root / "accounts.json", root / "salesforce" / "users.json",
           root / "pii_names.json", root / "index.json"]
    )


def test_seed_spec_validates_against_contract(spec):
    validate(spec, "CorpusSeedSpec")
    assert spec["seed"] == 20260914


def test_regeneration_is_byte_identical(regenerated):
    committed_files = _relative_json_files(MOCK_DIR)
    regen_files = _relative_json_files(regenerated)
    assert committed_files == regen_files, "generator wrote a different file set than committed"

    for rel in committed_files:
        committed_bytes = (MOCK_DIR / rel).read_bytes()
        regen_bytes = (regenerated / rel).read_bytes()
        assert committed_bytes == regen_bytes, "byte mismatch in %s" % rel


def test_every_generated_file_validates_against_its_schema():
    checked = 0
    for path in MOCK_DIR.glob("gong/calls/*.json"):
        validate(json.loads(path.read_text()), "GongCallFile")
        checked += 1
    for path in MOCK_DIR.glob("salesforce/cases/*.json"):
        validate(json.loads(path.read_text()), "SalesforceCaseFile")
        checked += 1
    validate(json.loads((MOCK_DIR / "accounts.json").read_text()), "MockAccountsFile")
    validate(json.loads((MOCK_DIR / "salesforce" / "users.json").read_text()), "SalesforceQueryResponse")
    validate(json.loads((MOCK_DIR / "pii_names.json").read_text()), "PiiNames")
    validate(json.loads((MOCK_DIR / "index.json").read_text()), "MockIndex")
    assert checked == 24 + 22


def test_counts_per_week_match_spec_minus_trap_slots(spec):
    index_doc = json.loads((MOCK_DIR / "index.json").read_text())
    generated = [e for e in index_doc["entries"] if not e["trap"]]
    trap = [e for e in index_doc["entries"] if e["trap"]]

    week_totals = {w["week"]: w for w in spec["week_totals"]}
    trap_counts = Counter((e["week"], e["kind"]) for e in trap)
    generated_counts = Counter((e["week"], e["kind"]) for e in generated)

    for week, totals in week_totals.items():
        expected_calls = totals["calls"] - trap_counts.get((week, "gong_call"), 0)
        expected_cases = totals["cases"] - trap_counts.get((week, "sfdc_case"), 0)
        assert generated_counts.get((week, "gong_call"), 0) == expected_calls, week
        assert generated_counts.get((week, "sfdc_case"), 0) == expected_cases, week

    # the pinned split from contracts/file_formats.md section 13
    assert generated_counts[("2026-W37", "gong_call")] == 8
    assert generated_counts[("2026-W37", "sfdc_case")] == 10
    assert generated_counts[("2026-W38", "gong_call")] == 9
    assert generated_counts[("2026-W38", "sfdc_case")] == 7
    assert generated_counts[("2026-W39", "gong_call")] == 7
    assert generated_counts[("2026-W39", "sfdc_case")] == 5


def test_index_lists_trap_slots_without_writing_them(spec):
    index_doc = json.loads((MOCK_DIR / "index.json").read_text())
    trap_ids_in_index = {e["id"] for e in index_doc["entries"] if e["trap"]}
    trap_ids_in_spec = {slot["id"] for slot in spec["trap_slots"]}
    assert trap_ids_in_index == trap_ids_in_spec
    # B2 must never write under data/mock/traps/ itself: check what the generator actually
    # produces, not the shared data/mock/traps/ directory, which is B3's own fixture output
    # and legitimately exists there once B3 has run.
    outputs = gc.generate(spec)
    assert not any(path.startswith("traps/") for path in outputs), (
        "B2's generator must never emit a path under traps/"
    )


def test_no_email_shaped_or_at_sign_text_in_generated_prose():
    for path in MOCK_DIR.glob("gong/calls/*.json"):
        doc = json.loads(path.read_text())
        for block in doc["transcript"]["transcript"]:
            for sentence in block["sentences"]:
                text = sentence["text"]
                assert "@" not in text, (path, text)
                assert "[EMAIL]" not in text, (path, text)
    for path in MOCK_DIR.glob("salesforce/cases/*.json"):
        doc = json.loads(path.read_text())
        for comment in doc["comments"]:
            body = comment["CommentBody"]
            assert "@" not in body, (path, body)
            assert "[EMAIL]" not in body, (path, body)


def test_no_em_or_en_dash_anywhere_in_gong_or_salesforce():
    for sub in ("gong", "salesforce"):
        for path in (MOCK_DIR / sub).rglob("*.json"):
            raw = path.read_text(encoding="utf-8")
            assert EM_DASH not in raw, path
            assert EN_DASH not in raw, path


def test_pii_names_includes_harold_pemberton_vance():
    doc = json.loads((MOCK_DIR / "pii_names.json").read_text())
    assert "Harold Pemberton-Vance" in doc["names"]
    assert len(doc["names"]) == len(set(doc["names"])), "names must be unique"


def test_accounts_file_has_nine_accounts_six_customers_three_prospects():
    doc = json.loads((MOCK_DIR / "accounts.json").read_text())
    accounts = doc["accounts"]
    assert len(accounts) == 9
    customers = [a for a in accounts if a["account_type"] == "customer"]
    prospects = [a for a in accounts if a["account_type"] == "prospect"]
    assert len(customers) == 6
    assert len(prospects) == 3


def test_users_file_has_four_standard_staff_and_nine_client_contacts():
    doc = json.loads((MOCK_DIR / "salesforce" / "users.json").read_text())
    records = doc["records"]
    staff = [r for r in records if r["UserType"] == "Standard"]
    clients = [r for r in records if r["UserType"] != "Standard"]
    assert len(staff) == 4
    assert len(clients) == 9
    assert all(r["IsActive"] for r in records)


def test_each_case_has_between_two_and_six_comments_and_withheld_ones_are_marked():
    total_cases = 0
    cases_with_private_comment = 0
    for path in MOCK_DIR.glob("salesforce/cases/*.json"):
        doc = json.loads(path.read_text())
        total_cases += 1
        n_comments = len(doc["comments"])
        assert 2 <= n_comments <= 6, path
        if any(not c["IsPublished"] for c in doc["comments"]):
            cases_with_private_comment += 1
    assert total_cases == 22
    # roughly a third of cases carry a private comment, per the brief
    assert cases_with_private_comment > 0


def test_each_generated_call_has_25_to_60_monologues_and_20_to_45_minute_duration():
    for path in MOCK_DIR.glob("gong/calls/*.json"):
        doc = json.loads(path.read_text())
        n_mono = len(doc["transcript"]["transcript"])
        assert 25 <= n_mono <= 60, path
        duration = doc["call"]["metaData"]["duration"]
        assert 20 * 60 <= duration <= 45 * 60, (path, duration)


def test_sentence_times_are_monotonic_within_each_call():
    for path in MOCK_DIR.glob("gong/calls/*.json"):
        doc = json.loads(path.read_text())
        prev_end = -1
        for block in doc["transcript"]["transcript"]:
            for sentence in block["sentences"]:
                assert sentence["start"] >= prev_end, path
                assert sentence["end"] > sentence["start"], path
                prev_end = sentence["end"]


def test_no_sentence_repeats_within_a_call_or_case():
    for path in MOCK_DIR.glob("gong/calls/*.json"):
        doc = json.loads(path.read_text())
        seen = []
        for block in doc["transcript"]["transcript"]:
            for sentence in block["sentences"]:
                seen.append(sentence["text"])
        assert len(seen) == len(set(seen)), (path, [t for t in set(seen) if seen.count(t) > 1])
    for path in MOCK_DIR.glob("salesforce/cases/*.json"):
        doc = json.loads(path.read_text())
        bodies = [c["CommentBody"] for c in doc["comments"]]
        assert len(bodies) == len(set(bodies)), path


def test_first_monologue_of_every_call_is_a_greeting():
    greetings = set(gc.GREETING_EXTERNAL) | set(gc.GREETING_INTERNAL)
    for path in MOCK_DIR.glob("gong/calls/*.json"):
        doc = json.loads(path.read_text())
        first_block = doc["transcript"]["transcript"][0]
        first_text = first_block["sentences"][0]["text"]
        assert first_text in greetings, (path, first_text)


def test_cli_entry_point_runs(tmp_path):
    import subprocess

    out_dir = tmp_path / "cli_out"
    result = subprocess.run(
        [sys.executable, str(TOOLS / "generate_corpus.py"),
         "--spec", str(SPEC_PATH), "--out", str(out_dir)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (out_dir / "index.json").exists()
