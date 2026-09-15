"""Tests for digest.pii.scrubber. Owned by B7. See contracts/INTERFACES.md,
section `digest.pii.scrubber`, and build/briefs/B7.md.

These tests do not depend on data/mock/pii_names.json or data/mock/traps/pii_names.json
existing on disk (another worker owns those files and may not have written them yet by the
time this file runs). Every test passes its own `names` list, or points `load_names` at a
tmp_path fixture it writes itself.
"""
from __future__ import annotations

import json

from digest.pii.scrubber import load_names, scrub, scrub_document

NAMES = ["Dana Ruiz", "Harold Pemberton-Vance", "Tomas Ehrlich"]

# The four planted values from build/briefs/SHARED_corpus_plan.md, trap T4(b).
PLANTED_EMAIL = "dana.whitfield@example.net"
PLANTED_PHONE = "(612) 555-0147"
PLANTED_ADDRESS = "4821 Larkspur Lane, Duluth, MN 55803"
PLANTED_NAME = "Harold Pemberton-Vance"


def test_planted_email_is_redacted():
    text = f"You can reach the donor at {PLANTED_EMAIL} if needed."
    clean, counts = scrub(text, names=NAMES)
    assert PLANTED_EMAIL not in clean
    assert "[EMAIL]" in clean
    assert counts == {"EMAIL": 1, "PHONE": 0, "ADDRESS": 0, "NAME": 0}


def test_planted_phone_is_redacted():
    text = f"His number on file is {PLANTED_PHONE} in case you need to follow up."
    clean, counts = scrub(text, names=NAMES)
    assert PLANTED_PHONE not in clean
    assert "[PHONE]" in clean
    assert counts == {"EMAIL": 0, "PHONE": 1, "ADDRESS": 0, "NAME": 0}


def test_planted_address_is_redacted():
    text = f"Mail the acknowledgement letter to {PLANTED_ADDRESS} this week."
    clean, counts = scrub(text, names=NAMES)
    assert PLANTED_ADDRESS not in clean
    assert "[ADDRESS]" in clean
    assert counts == {"EMAIL": 0, "PHONE": 0, "ADDRESS": 1, "NAME": 0}


def test_planted_name_is_redacted():
    text = f"The donor record was for {PLANTED_NAME}, a longtime supporter."
    clean, counts = scrub(text, names=NAMES)
    assert PLANTED_NAME not in clean
    assert "[NAME]" in clean
    assert counts == {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 1}


def test_all_four_planted_values_together():
    text = (
        f"Donor: {PLANTED_NAME}. Email {PLANTED_EMAIL}, phone {PLANTED_PHONE}, "
        f"mailing address {PLANTED_ADDRESS}."
    )
    clean, counts = scrub(text, names=NAMES)
    for value in (PLANTED_EMAIL, PLANTED_PHONE, PLANTED_ADDRESS, PLANTED_NAME):
        assert value not in clean
    assert counts == {"EMAIL": 1, "PHONE": 1, "ADDRESS": 1, "NAME": 1}


# --- phone formats -----------------------------------------------------------

PHONE_FORMATS = [
    "(612) 555-0147",
    "612-555-0147",
    "612.555.0147",
    "+1 612 555 0147",
    "6125550147",
]


def test_every_phone_format_is_caught():
    for phone in PHONE_FORMATS:
        text = f"Call me back at {phone} tomorrow."
        clean, counts = scrub(text, names=[])
        assert phone not in clean, f"failed to redact {phone!r}"
        assert clean.count("[PHONE]") == 1
        assert counts["PHONE"] == 1


# --- false positive guards ----------------------------------------------------

def test_year_is_not_redacted_as_phone():
    text = "We signed the renewal in 2026 and it starts again in 2027."
    clean, counts = scrub(text, names=[])
    assert clean == text
    assert counts["PHONE"] == 0


def test_dollar_amount_is_not_redacted_as_phone():
    text = "The invoice was for $4,821.00 and the prior one was $612.55."
    clean, counts = scrub(text, names=[])
    assert clean == text
    assert counts["PHONE"] == 0


def test_case_number_is_not_redacted():
    text = "This is the same issue as case 00147 from last quarter."
    clean, counts = scrub(text, names=[])
    assert clean == text
    assert counts == {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}


def test_salesforce_id_is_not_redacted():
    text = "The case id is 5008W00002aQpLrQAK, please reference it."
    clean, counts = scrub(text, names=[])
    assert clean == text
    assert counts == {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}


def test_call_id_is_not_redacted():
    text = "Call id 7782934451404 came through this morning."
    clean, counts = scrub(text, names=[])
    assert clean == text
    assert counts["PHONE"] == 0


def test_dates_and_times_are_not_redacted():
    text = (
        "The meeting is at 10:30 and the offset in the recording is 07:23. "
        "It was logged at 2026-09-08T15:00:00Z."
    )
    clean, counts = scrub(text, names=[])
    assert clean == text
    assert counts == {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}


def test_account_and_product_names_are_untouched_when_not_in_names_list():
    text = "Sunbelt Literacy Network uses the LMS product every week."
    clean, counts = scrub(text, names=NAMES)
    assert clean == text
    assert counts["NAME"] == 0


# --- names ---------------------------------------------------------------------

def test_hyphenated_surname_alone_is_caught():
    text = "Pemberton-Vance called in about the pledge reminder."
    clean, counts = scrub(text, names=NAMES)
    assert "Pemberton-Vance" not in clean
    assert "[NAME]" in clean
    assert counts["NAME"] == 1


def test_last_comma_first_is_caught():
    text = "Filed under Ruiz, Dana in the donor system."
    clean, counts = scrub(text, names=NAMES)
    assert "Ruiz, Dana" not in clean
    assert counts["NAME"] == 1


def test_name_matching_is_case_insensitive_and_word_bounded():
    text = "dana ruiz asked about her account, but Danarium Ruizova is unrelated."
    clean, counts = scrub(text, names=NAMES)
    assert "dana ruiz" not in clean.lower()
    assert "Danarium Ruizova" in clean
    assert counts["NAME"] == 1


# --- idempotency and byte-identical otherwise ---------------------------------

def test_scrub_is_idempotent():
    text = f"Reach {PLANTED_NAME} at {PLANTED_EMAIL} or {PLANTED_PHONE}."
    once, _ = scrub(text, names=NAMES)
    twice, counts_twice = scrub(once, names=NAMES)
    assert once == twice
    assert counts_twice == {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}


def test_500_word_transcript_three_plants_three_redactions_otherwise_identical():
    filler = " ".join(["word"] * 80)
    paragraph = (
        f"{filler} During the call the client mentioned reaching the donor at "
        f"{PLANTED_EMAIL} for a follow up. {filler} Later they read out a phone "
        f"number, {PLANTED_PHONE}, from the record on file. {filler} The donor in "
        f"question was {PLANTED_NAME}, a longtime supporter of the literacy program. "
        f"{filler} Nothing else in this paragraph should change at all. {filler}"
    )
    assert len(paragraph.split()) >= 400

    clean, counts = scrub(paragraph, names=NAMES)

    assert counts == {"EMAIL": 1, "PHONE": 1, "ADDRESS": 0, "NAME": 1}
    assert PLANTED_EMAIL not in clean
    assert PLANTED_PHONE not in clean
    assert PLANTED_NAME not in clean

    expected = (
        paragraph.replace(PLANTED_EMAIL, "[EMAIL]")
        .replace(PLANTED_PHONE, "[PHONE]")
        .replace(PLANTED_NAME, "[NAME]")
    )
    assert clean == expected


# --- load_names union ------------------------------------------------------------

def test_load_names_unions_two_files(tmp_path):
    base = tmp_path / "pii_names.json"
    traps = tmp_path / "traps_pii_names.json"
    base.write_text(json.dumps({"schema_version": "1.0.0", "names": ["Dana Ruiz"]}))
    traps.write_text(
        json.dumps({"schema_version": "1.0.0", "names": ["Harold Pemberton-Vance", "Dana Ruiz"]})
    )
    names = load_names([base, traps])
    assert sorted(n.lower() for n in names) == sorted(
        n.lower() for n in ["Dana Ruiz", "Harold Pemberton-Vance"]
    )


def test_load_names_missing_traps_file_is_skipped(tmp_path):
    base = tmp_path / "pii_names.json"
    missing_traps = tmp_path / "does_not_exist.json"
    base.write_text(json.dumps({"schema_version": "1.0.0", "names": ["Tomas Ehrlich"]}))
    names = load_names([base, missing_traps])
    assert names == ["Tomas Ehrlich"]


def test_load_names_single_path_matches_contract_signature(tmp_path):
    base = tmp_path / "pii_names.json"
    base.write_text(json.dumps({"schema_version": "1.0.0", "names": ["Priya Balan"]}))
    names = load_names(base)
    assert names == ["Priya Balan"]


# --- scrub_document --------------------------------------------------------------

def _make_doc():
    return {
        "schema_version": "1.0.0",
        "source": "gong",
        "source_id": "7782934451404",
        "title": f"Call with donor mention of {PLANTED_NAME}",
        "account_id": "ACC-0005",
        "account_name": "Sunbelt Literacy Network",
        "occurred_at": "2026-09-08T15:00:00Z",
        "doc_type": "call",
        "ingest_run_id": "2026-09-08T06:00Z",
        "participants": [
            {"id": "p-1", "name": PLANTED_NAME, "side": "client", "title": None},
        ],
        "turns": [
            {
                "ref": {
                    "call_id": "7782934451404",
                    "speaker_id": "1",
                    "speaker_name": "External Speaker",
                    "affiliation": "External",
                    "start_ms": 0,
                    "end_ms": 1000,
                },
                "speaker_id": "1",
                "speaker_side": "client",
                "text": (
                    f"The donor is {PLANTED_NAME}, reachable at {PLANTED_EMAIL} or "
                    f"{PLANTED_PHONE}, living at {PLANTED_ADDRESS}."
                ),
                "sentences": [
                    {
                        "start_ms": 0,
                        "end_ms": 500,
                        "text": f"The donor is {PLANTED_NAME}, reachable at {PLANTED_EMAIL}.",
                    },
                    {
                        "start_ms": 500,
                        "end_ms": 1000,
                        "text": f"His phone is {PLANTED_PHONE} and address is {PLANTED_ADDRESS}.",
                    },
                ],
            }
        ],
        "meta": {"withheld_comment_count": 0, "turn_count": 1, "soql": None},
    }


def test_scrub_document_redacts_turns_sentences_and_title():
    doc = _make_doc()
    clean_doc, counts = scrub_document(doc, names=NAMES)

    assert PLANTED_NAME not in clean_doc["title"]
    turn = clean_doc["turns"][0]
    assert PLANTED_EMAIL not in turn["text"]
    assert PLANTED_PHONE not in turn["text"]
    assert PLANTED_ADDRESS not in turn["text"]
    assert PLANTED_NAME not in turn["text"]
    for sentence in turn["sentences"]:
        assert PLANTED_EMAIL not in sentence["text"]
        assert PLANTED_PHONE not in sentence["text"]
        assert PLANTED_ADDRESS not in sentence["text"]
        assert PLANTED_NAME not in sentence["text"]

    # One occurrence per turn: sentences are scrubbed too but not counted twice.
    assert counts == {"EMAIL": 1, "PHONE": 1, "ADDRESS": 1, "NAME": 2}


def test_scrub_document_never_touches_ids_or_participants():
    doc = _make_doc()
    clean_doc, _ = scrub_document(doc, names=NAMES)

    assert clean_doc["source_id"] == doc["source_id"]
    assert clean_doc["account_id"] == doc["account_id"]
    assert clean_doc["turns"][0]["ref"] == doc["turns"][0]["ref"]
    assert clean_doc["turns"][0]["speaker_id"] == doc["turns"][0]["speaker_id"]
    # Participants carry the real name deliberately (speakers are not scrubbed).
    assert clean_doc["participants"] == doc["participants"]


def test_scrub_document_does_not_mutate_input():
    doc = _make_doc()
    original_text = doc["turns"][0]["text"]
    scrub_document(doc, names=NAMES)
    assert doc["turns"][0]["text"] == original_text
