"""The two reader agents.

The live calls behind these tests were made once on the extraction tier in `record` mode and
committed under `tests/fixtures/b9/responses/`. Everything here replays, so the suite is free
and gives the same answer twice. Re-record only when a prompt file changes, because the
replay key covers the system and user text.

What is actually being asserted is the reader's one promise: every verbatim it returns is an
exact substring of a turn it was shown, and that turn belongs to the client.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from digest.agents.readers import (
    SCHEMA_NAME,
    TIER,
    agent_for,
    manifest,
    prompt_for,
    prompt_meta,
    prompt_path,
    read_source,
    render_turns,
    render_user,
)
from digest.audit import Audit
from digest.contracts import validate
from digest.router import Router

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "b9"
RESPONSES = FIXTURES / "responses"
CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config" / "models.yaml"

RUN_ID = "2026-09-10T06:00Z"
DOCS = ("gong_call", "salesforce_case")

# The sentence timing marker the Gong template puts in front of each sentence.
MARKER = re.compile(r"\(\d+-\d+\) ")

# Fields the pipeline owns. A reader that returned one of these would be filling in work it
# has no evidence for, so the test looks for them anywhere in the output.
PIPELINE_OWNED = (
    "claim_id", "run_id", "captured_at", "account_id", "account_name", "account_type",
    "speaker_side", "prompt_hash", "model_tier", "speaker_name", "affiliation",
    "case_number", "author_id", "author_name", "created_at",
)


def load(name: str) -> dict:
    return json.loads((FIXTURES / ("%s.json" % name)).read_text(encoding="utf-8"))


def replay(doc: dict, tmp_path: pathlib.Path) -> tuple[dict, Audit]:
    router = Router(CONFIG, mode="replay", responses_dir=RESPONSES)
    audit = Audit(RUN_ID, tmp_path)
    return read_source(doc, router, audit), audit


def resolve(claim: dict, doc: dict) -> dict | None:
    """The turn a claim cites, by the same rule digest.verify uses. None when unresolved."""
    ref = claim["source_ref"]
    for turn in doc["turns"]:
        turn_ref = turn["ref"]
        if claim["source"] == "gong":
            if (turn_ref["call_id"] == ref["call_id"]
                    and turn_ref["speaker_id"] == ref["speaker_id"]
                    and turn_ref["start_ms"] == ref["start_ms"]
                    and turn_ref["end_ms"] == ref["end_ms"]):
                return turn
        elif turn_ref["comment_id"] == ref["comment_id"]:
            return turn
    return None


def walk(node, seen: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            seen.append(key)
            walk(value, seen)
    elif isinstance(node, list):
        for item in node:
            walk(item, seen)


# -- the fixtures and the prompt files -------------------------------------------


@pytest.mark.parametrize("name", DOCS)
def test_fixture_is_a_valid_source_document(name):
    validate(load(name), "SourceDocument")


@pytest.mark.parametrize("source", ["gong", "salesforce"])
def test_prompt_file_frontmatter(source):
    meta = prompt_meta(source)
    assert meta["schema"] == SCHEMA_NAME
    assert meta["tier"] == TIER
    assert re.fullmatch(r"\d+\.\d+\.\d+", meta["prompt_version"])
    system, template = prompt_for(source)
    assert system and template
    assert "{{turns}}" in template


@pytest.mark.parametrize("source", ["gong", "salesforce"])
def test_prompt_file_is_plain_ascii_without_dashes(source):
    text = prompt_path(source).read_text(encoding="utf-8")
    # Escapes, not the characters themselves: the repository bans both outright.
    assert "\u2014" not in text and "\u2013" not in text
    assert text.isascii()


def test_prompt_names_the_non_claim_example():
    # Trap T4(c). The employee sentence has to be named in the prompt, not implied.
    for source in ("gong", "salesforce"):
        system, _ = prompt_for(source)
        assert "A lot of our customers ask for this" in system
        assert "[EMAIL]" in system and "[NAME]" in system


def test_agent_for_rejects_an_unknown_source():
    with pytest.raises(ValueError):
        agent_for("zendesk")


def test_manifest_lists_both_readers():
    agents = {row["agent"]: row for row in manifest()["agents"]}
    assert set(agents) == {"gong_reader", "sfdc_reader"}
    for row in agents.values():
        assert row["tier"] == TIER and row["schema"] == SCHEMA_NAME
        assert re.fullmatch(r"[0-9a-f]{64}", row["prompt_sha256"])


# -- rendering -------------------------------------------------------------------


def test_gong_turn_body_strips_back_to_the_verified_text():
    # This is the whole reason the markers are safe: take them out and what is left is the
    # exact string the citation verifier tests a verbatim against.
    doc = load("gong_call")
    rendered = render_turns(doc)
    for turn in doc["turns"]:
        assert turn["text"] in MARKER.sub("", rendered)


def test_turn_headers_carry_the_locator_and_the_side():
    doc = load("gong_call")
    rendered = render_turns(doc)
    assert "[turn 1 | speaker_id 8801 | Denise Kohler | client | 300000-321000]" in rendered
    assert "[turn 2 | speaker_id 3310 | Priya Natarajan | momentive | 321000-333000]" in rendered

    case = load("salesforce_case")
    assert "comment_id 00aB000001kLmNoIAO" in render_turns(case)
    assert "| client |" in render_turns(case)


@pytest.mark.parametrize("name", DOCS)
def test_rendered_user_prompt_has_no_unfilled_placeholder(name):
    doc = load(name)
    user = render_user(doc)
    assert "{{" not in user
    assert doc["source_id"] in user
    assert doc["account_name"] in user


def test_salesforce_prompt_never_shows_a_private_comment():
    # The connector filtered them out. The prompt must not leak the count as text the model
    # could mistake for content, and there is nothing here to quote from.
    doc = load("salesforce_case")
    user = render_user(doc)
    assert "churn risk if the invoice thing drags on" not in user
    assert len([line for line in user.splitlines() if line.startswith("[turn ")]) == 2


# -- the replayed calls ----------------------------------------------------------


@pytest.mark.parametrize("name", DOCS)
def test_reader_output_validates(name, tmp_path):
    doc = load(name)
    out, _ = replay(doc, tmp_path)
    validate(out, "ReaderOutput")
    assert out["source"] == doc["source"]
    assert out["source_id"] == doc["source_id"]
    if out["claims"]:
        assert out["no_claims_reason"] is None


@pytest.mark.parametrize("name", DOCS)
def test_every_verbatim_is_an_exact_substring_of_the_cited_turn(name, tmp_path):
    doc = load(name)
    out, _ = replay(doc, tmp_path)
    assert out["claims"], "the fixture was built to contain a client claim"
    for claim in out["claims"]:
        turn = resolve(claim, doc)
        assert turn is not None, "citation did not resolve: %r" % (claim["source_ref"],)
        assert claim["verbatim"] in turn["text"]
        assert "..." not in claim["verbatim"]
        assert 8 <= len(claim["verbatim"].split()) <= 60


@pytest.mark.parametrize("name", DOCS)
def test_no_claim_is_attributed_to_a_momentive_speaker(name, tmp_path):
    # Trap T4(c) in both fixtures: an employee says "A lot of our customers ask for this."
    # A claim quoting it would resolve to a turn whose side is momentive, and the verifier
    # rejects those, so the reader must not produce one in the first place.
    doc = load(name)
    out, _ = replay(doc, tmp_path)
    for claim in out["claims"]:
        turn = resolve(claim, doc)
        assert turn["speaker_side"] == "client"
        assert "A lot of our customers ask for this" not in claim["verbatim"]


def test_a_redaction_placeholder_survives_as_written(tmp_path):
    doc = load("gong_call")
    out, _ = replay(doc, tmp_path)
    quoted = " ".join(claim["verbatim"] for claim in out["claims"])
    assert "[NAME]" in quoted and "[EMAIL]" in quoted
    # Nothing that looks like a real address was invented to fill the placeholder in.
    assert "@" not in quoted.replace("[EMAIL]", "")


@pytest.mark.parametrize("name", DOCS)
def test_reader_fills_nothing_the_pipeline_owns(name, tmp_path):
    out, _ = replay(load(name), tmp_path)
    keys: list[str] = []
    walk(out, keys)
    assert not [k for k in keys if k in PIPELINE_OWNED]


# -- the audit trail -------------------------------------------------------------


@pytest.mark.parametrize("name", DOCS)
def test_one_read_event_for_the_document_and_the_router_logs_the_rest(name, tmp_path):
    doc = load(name)
    _, audit = replay(doc, tmp_path)
    events = audit.events()
    reads = [e for e in events if e["action"] == "read"]
    assert len(reads) == 1
    assert reads[0]["agent"] == agent_for(doc["source"])
    assert reads[0]["target"] == doc["source_id"]
    assert reads[0]["stage"] == "extract"
    assert reads[0]["detail"]["turn_count"] == doc["meta"]["turn_count"]

    assert [e["action"] for e in events] == ["read", "call_model", "validate"]
    for event in events[1:]:
        assert event["model_tier"] == TIER
        assert event["target"] == SCHEMA_NAME


def test_the_read_event_carries_no_source_text(tmp_path):
    doc = load("gong_call")
    _, audit = replay(doc, tmp_path)
    detail = json.dumps(audit.events()[0]["detail"])
    for turn in doc["turns"]:
        assert turn["text"][:40] not in detail


# -- the empty answer ------------------------------------------------------------


class StubRouter:
    """Stands in for the router when the point of the test is what read_source does with the
    answer, not what the model said."""

    def __init__(self, data: dict) -> None:
        self.data = data
        self.calls: list[dict] = []

    def complete(self, tier, system, user, schema_name, *, run_id, agent, audit):
        self.calls.append({"tier": tier, "schema_name": schema_name, "run_id": run_id,
                           "agent": agent, "system": system, "user": user})
        return {"data": self.data, "replayed": False}


def test_no_claims_answer_is_returned_untouched(tmp_path):
    doc = load("gong_call")
    empty = {
        "schema_version": "1.0.0",
        "source": "gong",
        "source_id": doc["source_id"],
        "claims": [],
        "no_claims_reason": "Only the Momentive Software side spoke, asking discovery questions.",
    }
    validate(empty, "ReaderOutput")
    router = StubRouter(empty)
    out = read_source(doc, router, Audit(RUN_ID, tmp_path))
    assert out == empty
    assert out is router.data


def test_read_source_asks_for_the_extraction_tier_and_the_reader_schema(tmp_path):
    doc = load("salesforce_case")
    router = StubRouter({"schema_version": "1.0.0", "source": "salesforce",
                         "source_id": doc["source_id"], "claims": [], "no_claims_reason": "none"})
    read_source(doc, router, Audit(RUN_ID, tmp_path))
    call = router.calls[0]
    assert call["tier"] == TIER
    assert call["schema_name"] == SCHEMA_NAME
    assert call["agent"] == "sfdc_reader"
    assert call["run_id"] == RUN_ID
    # The system prompt is the stable, cacheable half; the document is in the user turn.
    assert doc["source_id"] not in call["system"]
    assert doc["turns"][0]["text"] in call["user"]
