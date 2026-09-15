"""The analyst: retrieval, the prompt file, and three real recorded questions replayed.

The analyst has no source access at all. `search_store` is asserted directly against a
small fixture store built with `Store`'s own public API (two themes, two claims, nothing
else), and `ask` is asserted end to end through three recordings made once against a Claude
seat in `tests/fixtures/b14/record_live.py`, the up to three live calls B14's brief allows.
Replaying them here costs nothing and touches no network, and it is the same router code
path a live run uses, only reading instead of calling out.

One thing that recording script found and documents in full: `AnalystAnswer.schema.json`
carries a top level `allOf`, which the default provider's native structured output path
cannot serve because the Anthropic API refuses a top level `oneOf`/`allOf`/`anyOf` inside a
forced tool's `input_schema`. Neither the schema nor the seat adapter are in B14's
owns_paths, so the recordings were made through the router's own `schema_in_prompt`
negotiation path instead, which never builds a tool call and already exists for exactly
this situation. The router still validates every one of these recordings against the real
contract, both here and when they were written.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"
FIXTURES = REPO / "tests" / "fixtures" / "b14"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(FIXTURES) not in sys.path:
    sys.path.insert(0, str(FIXTURES))

from build_fixture_store import (  # noqa: E402
    CLAIM_IMPORT,
    CLAIM_RENEWAL,
    QUESTIONS,
    RUN_ID,
    THEME_IMPORT,
    THEME_RENEWAL,
    build_store,
)

from digest.agents.analyst.analyst import AGENT, SCHEMA_NAME, TIER, ask, prompt_for  # noqa: E402
from digest.agents.analyst.retrieval import search_store  # noqa: E402
from digest.audit import Audit  # noqa: E402
from digest.contracts import validate  # noqa: E402
from digest.errors import ContractViolation  # noqa: E402
from digest.router import TIERS, Router  # noqa: E402
from digest.store import Store  # noqa: E402

CONFIG = REPO / "config" / "models.yaml"
RESPONSES = FIXTURES / "responses"

ALL_CLAIM_IDS = {CLAIM_RENEWAL["claim_id"], CLAIM_IMPORT["claim_id"]}
ALL_THEME_IDS = {THEME_RENEWAL["theme_id"], THEME_IMPORT["theme_id"]}


class NoNetworkProvider:
    """A provider that fails loudly if anything tries to call out.

    Used for every replay test: replay mode never needs a provider at all, so a call
    reaching this one is the test finding a bug rather than a network flake.
    """

    name = "no-network"

    def capabilities(self) -> dict:
        return {"native_structured": False, "strict_tools": False,
                "thinking_style": "adaptive", "effort": True}

    def translate_model_id(self, canonical_model_id: str) -> str:
        return canonical_model_id

    def complete(self, *args, **kwargs):
        raise AssertionError("replay must not call out")


@pytest.fixture()
def store(tmp_path: pathlib.Path) -> Store:
    return build_store(tmp_path / "bi-theme-digest-store")


def _replay_router() -> Router:
    router = Router(CONFIG, mode="replay", responses_dir=RESPONSES)
    router.set_provider(NoNetworkProvider())
    return router


def _claim_ids_by_theme() -> dict[str, set[str]]:
    return {
        THEME_RENEWAL["theme_id"]: set(THEME_RENEWAL["evidence"]),
        THEME_IMPORT["theme_id"]: set(THEME_IMPORT["evidence"]),
    }


def _assert_citations_resolve(answer: dict) -> None:
    """Every citation names a theme and claim that really exist in the fixture store."""
    by_theme = _claim_ids_by_theme()
    for citation in answer["citations"]:
        assert citation["theme_id"] in ALL_THEME_IDS, citation
        assert citation["claim_id"] in by_theme[citation["theme_id"]], citation


# --------------------------------------------------------------------------- the prompt file


def test_the_prompt_file_is_versioned_for_the_narrative_tier_not_a_tier_called_analyst():
    """There are only three runtime tiers. The analyst role asks for narrative."""
    system, template = prompt_for()
    assert "{question}" in template and "{context}" in template
    assert TIER == "narrative"
    assert TIER in TIERS and AGENT not in TIERS  # there are only three runtime tiers
    assert "cite the theme id and the claim id" in system.lower()
    assert SCHEMA_NAME == "AnalystAnswer"
    assert AGENT == "analyst"


def test_a_prompt_file_with_the_wrong_declared_tier_is_rejected(tmp_path, monkeypatch):
    import digest.agents.analyst.analyst as analyst_module

    bad = tmp_path / "bad.prompt.md"
    bad.write_text(
        "---\nprompt_version: \"1.0.0\"\nschema: AnalystAnswer\ntier: analyst\nagent: analyst\n"
        "---\nsystem\n---\nuser {question} {context}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(analyst_module, "PROMPT_PATH", bad)
    analyst_module._load_prompt.cache_clear()
    with pytest.raises(ContractViolation):
        analyst_module.prompt_for()
    analyst_module._load_prompt.cache_clear()


# --------------------------------------------------------------------------- retrieval


def test_search_store_finds_the_one_theme_the_question_is_about(store: Store):
    hits = search_store(store, QUESTIONS["supported"], k=5)
    assert [h["theme_id"] for h in hits] == ["THEME-0003"]
    assert hits[0]["claim_ids"] == ["e7e3c117f5c5"]
    assert hits[0]["title"] == THEME_RENEWAL["title"]
    assert len(hits[0]["snippet"]) <= 300


def test_search_store_returns_nothing_for_an_unrelated_question(store: Store):
    assert search_store(store, QUESTIONS["unsupported"], k=5) == []


def test_search_store_finds_both_themes_when_the_question_needs_both(store: Store):
    hits = search_store(store, QUESTIONS["two_theme"], k=5)
    assert {h["theme_id"] for h in hits} == {"THEME-0003", "THEME-0007"}
    claim_ids = {cid for h in hits for cid in h["claim_ids"]}
    assert claim_ids == ALL_CLAIM_IDS


def test_search_store_respects_k(store: Store):
    assert len(search_store(store, QUESTIONS["two_theme"], k=1)) == 1


def test_search_store_orders_by_match_score_then_by_theme_score_then_by_id(store: Store):
    hits = search_store(store, "renewal registration import invoice", k=5)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_search_store_touching_a_theme_logs_a_read_audit_event(store: Store):
    audit = Audit(RUN_ID, store.path)
    store.attach_audit(audit)
    search_store(store, QUESTIONS["two_theme"], k=5)
    read_targets = {e["target"] for e in audit.events() if e["action"] == "read"}
    assert "THEME-0003" in read_targets
    assert "THEME-0007" in read_targets
    assert "themes/_INDEX.md" in read_targets


# --------------------------------------------------------------------------- ask, replayed


def test_the_supported_question_cites_the_real_theme_and_claim(store: Store):
    audit = Audit(RUN_ID, store.path)
    answer = ask(QUESTIONS["supported"], store, _replay_router(), audit)
    validate(answer, "AnalystAnswer")
    assert answer["supported"] is True
    assert answer["citations"], "a supported answer must carry at least one citation"
    _assert_citations_resolve(answer)
    assert answer["decline_reason"] is None


def test_the_unsupported_question_declines_with_no_citations(store: Store):
    audit = Audit(RUN_ID, store.path)
    answer = ask(QUESTIONS["unsupported"], store, _replay_router(), audit)
    validate(answer, "AnalystAnswer")
    assert answer["supported"] is False
    assert answer["citations"] == []
    assert answer["decline_reason"]


def test_the_two_theme_question_cites_both_themes(store: Store):
    audit = Audit(RUN_ID, store.path)
    answer = ask(QUESTIONS["two_theme"], store, _replay_router(), audit)
    validate(answer, "AnalystAnswer")
    assert answer["supported"] is True
    _assert_citations_resolve(answer)
    cited_themes = {c["theme_id"] for c in answer["citations"]}
    assert cited_themes == {"THEME-0003", "THEME-0007"}


def test_ask_logs_the_model_call_on_the_narrative_tier(store: Store):
    audit = Audit(RUN_ID, store.path)
    ask(QUESTIONS["supported"], store, _replay_router(), audit)
    call_events = [e for e in audit.events() if e["action"] == "call_model"]
    assert call_events and all(e["model_tier"] == "narrative" for e in call_events)
    assert any(e["action"] == "validate" for e in audit.events())


def test_a_replay_miss_is_fatal_and_never_falls_back_to_a_guess(store: Store):
    from digest.errors import ReplayMiss

    audit = Audit(RUN_ID, store.path)
    with pytest.raises(ReplayMiss):
        ask("a question nobody recorded an answer for", store, _replay_router(), audit)


# --------------------------------------------------------------------------- the recordings


def _recorded_requests() -> list[dict]:
    import json

    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESPONSES.glob("*.json"))]


def test_three_recordings_exist_one_per_allowed_live_call():
    docs = _recorded_requests()
    assert len(docs) == 3
    for doc in docs:
        validate(doc, "RecordedResponse")
        assert doc["request"]["tier"] == "narrative"
        assert doc["request"]["schema_name"] == "AnalystAnswer"
        assert doc["request"]["agent"] == "analyst"
        validate(doc["result"]["data"], "AnalystAnswer")


def test_the_recorded_cost_matches_the_pricing_table():
    router = Router(CONFIG)
    for doc in _recorded_requests():
        r = doc["result"]
        assert router.cost(r["model_id"], r["tokens_in"], r["tokens_out"],
                           r["cache_read"], r["cache_write"]) == r["cost_usd"]
