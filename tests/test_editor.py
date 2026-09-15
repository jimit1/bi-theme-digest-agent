"""The editor: prompts, the four read only tools, the two calls, and the cross checks.

The interesting tests here replay two real synthesis tier calls recorded against the
fixture in `tests/fixtures/b12/`. They assert the judgment the editor exists for: that two
descriptions of one billing failure in different vocabularies land on one theme, that one
capability under two product names lands on one theme carrying both names, that a claim
which plainly belongs to an existing theme is an append rather than a new theme, and that a
prospect is decided and labelled as a prospect rather than dressed up as customer evidence.

Everything else is deterministic and tested against stubs, because a cross check that needs
a model call to prove it is a cross check nobody will run.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib

import pytest

from digest.agents.editor import editor as ed
from digest.agents.editor.tools import TOOL_NAMES, EditorTools
from digest.audit import Audit
from digest.errors import ContractViolation, SchemaRejected
from digest.router import Router, retry_user_text

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "b12"
RESPONSES = FIXTURES / "responses"
MODELS_YAML = REPO_ROOT / "config" / "models.yaml"


def _load_scenario():
    spec = importlib.util.spec_from_file_location("b12_scenario", FIXTURES / "scenario.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scenario = _load_scenario()


# --------------------------------------------------------------------------- helpers


def recorded_proposal() -> dict:
    """The EditorProposal from the committed recording, straight off disk."""
    for path in sorted(RESPONSES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["request"]["schema_name"] == "EditorProposal":
            return copy.deepcopy(doc["result"]["data"])
    raise AssertionError("no EditorProposal recording in %s" % RESPONSES)


def recorded_theme_request() -> dict:
    """The EditorThemeRequest from the committed recording: what call one asked to open."""
    for path in sorted(RESPONSES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["request"]["schema_name"] == "EditorThemeRequest":
            return copy.deepcopy(doc["result"]["data"])
    raise AssertionError("no EditorThemeRequest recording in %s" % RESPONSES)


def configured_model_ids() -> set[str]:
    """The model ids config/models.yaml names. The only runtime file allowed to name one."""
    import yaml

    config = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8"))
    return {block["model"] for block in config["tiers"].values()}


class StubRouter:
    """Returns canned documents in order and remembers what it was asked."""

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def complete(self, tier, system, user, schema_name, *, run_id, agent, audit,
                 stage=None) -> dict:
        self.calls.append({"tier": tier, "system": system, "user": user,
                           "schema_name": schema_name, "run_id": run_id, "agent": agent,
                           "stage": stage})
        if not self.payloads:
            raise AssertionError("StubRouter ran out of payloads on call %d" % len(self.calls))
        return {"data": copy.deepcopy(self.payloads.pop(0))}


@pytest.fixture()
def store(tmp_path):
    return scenario.build_store(tmp_path / "store")


@pytest.fixture()
def audit(tmp_path):
    return Audit(scenario.RUN_ID, tmp_path / "store")


@pytest.fixture()
def replay_router():
    return Router(MODELS_YAML, mode="replay", responses_dir=RESPONSES)


def decision_for(proposal: dict, claim_id: str) -> dict:
    matches = [d for d in proposal["decisions"] if d["claim_id"] == claim_id]
    assert len(matches) == 1, "claim %s has %d decisions" % (claim_id, len(matches))
    return matches[0]


# --------------------------------------------------------------------------- prompt files


@pytest.mark.parametrize(
    "name, schema_name, version",
    [(ed.THEME_REQUEST_PROMPT, "EditorThemeRequest", "1.0.0"),
     (ed.EDITOR_PROMPT, "EditorProposal", "1.1.0")],
)
def test_prompt_file_is_versioned_and_asks_for_the_synthesis_tier(name, schema_name, version):
    prompt = ed.load_prompt(name)
    assert prompt.tier == "synthesis"
    assert prompt.schema == schema_name
    assert prompt.version == version
    assert len(prompt.sha256) == 64
    assert prompt.system and prompt.user_template
    # A model id never appears in a prompt. Application code asks for a tier, and the ids
    # are read out of the one runtime file allowed to name them rather than written here.
    for model_id in configured_model_ids():
        assert model_id not in prompt.system
        assert model_id not in prompt.user_template


def test_editor_prompt_carries_the_two_judgment_cases_it_has_to_survive():
    system = ed.load_prompt(ed.EDITOR_PROMPT).system
    assert "SAME theme" in system and "DIFFERENT themes" in system
    assert "event check-in" in system and "attendee kiosk" in system
    assert "aliases" in system and "reconciliations" in system
    # The reconciliation must be built from what clients said, never from staff written text.
    assert "subject line" in system
    # No write tool, and the reader is a human.
    assert "no write tool" in system.lower()


def test_editor_prompt_states_the_merge_rule_that_stops_over_splitting():
    """1.1.0. A theme is the underlying problem, and append beats open when it is close."""
    system = ed.load_prompt(ed.EDITOR_PROMPT).system
    # Collapsed, because the prompt is hard wrapped and a rule can straddle two lines.
    lower = " ".join(system.lower().split())
    # A theme is the problem a product manager would name, not a facet or a wording.
    assert "underlying problem" in lower
    assert "not a facet" in lower
    # The two merge tests.
    assert "fixing one would fix the other" in lower
    assert "same product behaviour is behind both" in lower
    # Cold start: group first, then one theme per group.
    assert "cold start" in lower
    assert "one theme per group" in lower
    # Open is the exception and carries the difference; append is the default.
    assert "prefer append" in lower
    assert "say in the reason what makes it a different problem" in lower
    # The worked contrast: one pair that merges, one pair that shares a word and splits.
    assert "worked contrast" in lower
    assert "one shared word" in lower


def test_user_templates_carry_only_volatile_content():
    request = ed.load_prompt(ed.THEME_REQUEST_PROMPT)
    proposal = ed.load_prompt(ed.EDITOR_PROMPT)
    for token in ("{{WEEK}}", "{{RUN_ID}}", "{{THEME_INDEX}}", "{{CLAIMS}}",
                  "{{ENRICHMENT}}", "{{QUIET_OR_STALE}}"):
        assert token in request.user_template
        assert token in proposal.user_template
    assert "{{THEME_BODIES}}" in proposal.user_template
    assert "{{THEME_BODIES}}" not in request.user_template


def test_render_leaves_no_placeholder_behind():
    filled = ed.render("a {{X}} b {{Y}}", {"X": "one", "Y": "two"})
    assert filled == "a one b two"


def test_manifest_names_four_tools_and_both_prompts():
    made = ed.manifest()
    assert made["tier"] == "synthesis"
    assert made["tools"] == list(TOOL_NAMES)
    assert set(made["prompts"]) == {"theme_request", "proposal"}
    assert all(len(p["sha256"]) == 64 for p in made["prompts"].values())


# --------------------------------------------------------------------------- the tools


def test_the_tool_surface_is_exactly_four_read_only_callables():
    assert TOOL_NAMES == ("read_theme_index", "read_theme", "list_run_claims", "read_account")
    public = {n for n in dir(EditorTools) if not n.startswith("_")}
    assert public == set(TOOL_NAMES)
    for forbidden in ("write", "commit", "append", "file", "approve", "delete"):
        assert not any(forbidden in name for name in public)


def test_every_tool_logs_a_read_event(store, audit):
    tools = EditorTools(store, audit, scenario.WEEK, claims=scenario.RUN_CLAIMS,
                        enrichment=scenario.ENRICHMENT)
    tools.read_theme_index()
    tools.read_theme("THEME-0001")
    tools.list_run_claims()
    tools.read_account("ACC-0001")
    events = [e for e in audit.events() if e["agent"] == "editor"]
    assert len(events) == 4
    assert {e["action"] for e in events} == {"read"}
    assert {e["stage"] for e in events} == {"edit"}
    assert [e["target"] for e in events] == [
        "themes/_INDEX.md", "THEME-0001", "evidence/claims", "ACC-0001"]


def test_list_run_claims_falls_back_to_the_store_for_the_week(store, audit):
    store.append_claims(scenario.INGEST_RUN, scenario.RUN_CLAIMS)
    tools = EditorTools(store, audit, scenario.WEEK, enrichment=scenario.ENRICHMENT)
    assert len(tools.list_run_claims()) == len(scenario.RUN_CLAIMS)


def test_read_account_rejects_an_account_this_run_does_not_have(store, audit):
    tools = EditorTools(store, audit, scenario.WEEK, claims=scenario.RUN_CLAIMS,
                        enrichment=scenario.ENRICHMENT)
    with pytest.raises(ContractViolation):
        tools.read_account("ACC-9999")


# --------------------------------------------------------------------------- the calendar


def test_run_id_and_build_date_match_the_pinned_calendar():
    assert ed.build_date_for_week("2026-W37").isoformat() == "2026-09-14"
    assert ed.run_id_for_week("2026-W37") == "2026-09-14T07:00Z"
    assert ed.run_id_for_week("2026-W38") == "2026-09-21T07:00Z"
    with pytest.raises(ContractViolation):
        ed.run_id_for_week("week 37")


def test_quiet_or_stale_is_computed_by_code_not_by_the_model(store):
    index = [dict(line) for line in store.read_theme_index()]
    flagged = ed.quiet_or_stale_themes(index, ed.build_date_for_week(scenario.WEEK))
    assert [item["theme_id"] for item in flagged] == ["THEME-0002"]
    assert flagged[0]["stale"] is True
    assert flagged[0]["days_since_last_update"] == 21


# ------------------------------------------------------------------- the recorded run


def test_run_editor_replays_two_recorded_synthesis_calls(store, audit, replay_router):
    proposal = ed.run_editor(scenario.WEEK, scenario.RUN_CLAIMS, scenario.ENRICHMENT,
                             store, replay_router, audit)
    ids = scenario.claims_by_topic()

    # Every claim is decided exactly once, and every decision carries a reason a product
    # manager could act on rather than a restatement of the claim's product area.
    assert len(proposal["decisions"]) == len(scenario.RUN_CLAIMS)
    assert {d["claim_id"] for d in proposal["decisions"]} == set(ids.values())
    for decision in proposal["decisions"]:
        assert len(decision["reason"].split()) >= 8

    # T1: one billing failure, two finance vocabularies, two accounts, ONE theme.
    first = decision_for(proposal, ids["renewal_statement"])
    second = decision_for(proposal, ids["mid_year_upgrade"])
    assert first["theme_id"] == second["theme_id"]

    # T2: one capability, two product names, ONE theme carrying both names.
    checkin = decision_for(proposal, ids["event_checkin"])
    kiosk = decision_for(proposal, ids["attendee_kiosk"])
    assert checkin["theme_id"] == kiosk["theme_id"]
    events_theme = checkin["theme_id"]
    assert events_theme.startswith("NEW-")
    new_theme = next(t for t in proposal["new_themes"] if t["placeholder"] == events_theme)
    aliases = " ; ".join(new_theme["aliases"]).lower()
    assert "event check-in" in aliases
    assert "attendee kiosk" in aliases

    # The reconciliation is named once, from the words the clients used.
    reconciliations = [r for r in proposal["digest"]["reconciliations"]
                       if r["theme_id_or_placeholder"] == events_theme]
    assert len(reconciliations) == 1
    names = " ; ".join(reconciliations[0]["names"]).lower()
    assert "event check-in" in names and "attendee kiosk" in names

    # The over-splitting pair: one behaviour, two facets. A frequency the donor did not ask
    # for and a channel the donor opted out of are both the platform ignoring the donor's
    # communication preference on pledge reminders, so they are ONE theme and not two.
    frequency = decision_for(proposal, ids["pledge_frequency"])
    channel = decision_for(proposal, ids["pledge_channel"])
    assert frequency["theme_id"] == channel["theme_id"], (
        "pledge frequency and pledge channel were split across %s and %s"
        % (frequency["theme_id"], channel["theme_id"]))

    # The claim that plainly belongs to a theme already in the store is an append.
    existing = decision_for(proposal, ids["export_row_cap"])
    assert existing["action"] == "append"
    assert existing["theme_id"] == "THEME-0001"

    # The prospect is decided, and the digest says it is a prospect rather than a customer.
    prospect = decision_for(proposal, ids["prospect_scorm"])
    assert prospect["action"] == "open"
    prospect_prose = " ".join(
        [s["body"] for s in proposal["digest"]["sections"]
         if s["theme_id_or_placeholder"] == prospect["theme_id"]]
        + [r["rationale"] for r in proposal["theme_rationales"]
           if r["theme_id_or_placeholder"] == prospect["theme_id"]])
    assert "prospect" in prospect_prose.lower()

    # The quiet theme gets exactly one line, and the editor invented no theme for it.
    assert len(proposal["digest"]["quiet_or_stale_notes"]) == 1
    assert "THEME-0002" in proposal["digest"]["quiet_or_stale_notes"][0]

    assert proposal["week"] == scenario.WEEK
    assert proposal["run_id"] == scenario.RUN_ID


def test_the_recorded_run_reads_only_the_themes_it_asked_for(store, audit, replay_router):
    ed.run_editor(scenario.WEEK, scenario.RUN_CLAIMS, scenario.ENRICHMENT, store,
                  replay_router, audit)
    events = audit.events()
    opened = [e["target"] for e in events
              if e["agent"] == "editor" and e["action"] == "read"
              and str(e["target"]).startswith("THEME-")]
    # Exactly the ids call one asked for, in the order it asked for them, and nothing else.
    assert opened == recorded_theme_request()["needs_themes"]
    assert opened, "call one asked for no theme at all"
    proposed = [e for e in events if e["action"] == "propose"]
    assert len(proposed) == 1
    assert proposed[0]["detail"]["themes_opened"] == len(opened)
    # Not one write event from the editor. Code performs every write.
    assert not [e for e in events if e["agent"] == "editor" and e["action"] == "write"]


def test_an_unknown_theme_id_is_dropped_with_a_reject_event(store, audit):
    router = StubRouter([
        {"schema_version": "1.0.0", "needs_themes": ["THEME-0001", "THEME-9999"]},
        recorded_proposal(),
    ])
    ed.run_editor(scenario.WEEK, scenario.RUN_CLAIMS, scenario.ENRICHMENT, store, router,
                  audit)
    rejects = [e for e in audit.events() if e["action"] == "reject"]
    assert [e["target"] for e in rejects] == ["THEME-9999"]
    assert rejects[0]["outcome"] == "rejected"
    assert "THEME-9999" not in router.calls[1]["user"]


# --------------------------------------------------------------------------- cross checks


def test_validate_proposal_accepts_the_recorded_proposal(store):
    index = [dict(line) for line in store.read_theme_index()]
    ed.validate_proposal(recorded_proposal(), index, scenario.RUN_CLAIMS,
                         scenario.ENRICHMENT)


def _mutate(fn):
    proposal = recorded_proposal()
    fn(proposal)
    return proposal


def _unknown_claim(proposal):
    proposal["decisions"][0]["claim_id"] = "aaaaaaaaaaaa"


def _unknown_theme(proposal):
    for decision in proposal["decisions"]:
        if decision["action"] == "append":
            decision["theme_id"] = "THEME-9999"


def _undefined_placeholder(proposal):
    # Drop the definition of a placeholder the decisions still point at, whichever it is,
    # so the mutation survives a re-recording that opens a different number of themes.
    orphan = next(d["theme_id"] for d in proposal["decisions"] if d["action"] == "open")
    proposal["new_themes"] = [t for t in proposal["new_themes"]
                              if t["placeholder"] != orphan]


def _claim_decided_twice(proposal):
    proposal["decisions"].append(copy.deepcopy(proposal["decisions"][0]))


def _claim_never_decided(proposal):
    proposal["decisions"].pop()


def _open_names_an_existing_theme(proposal):
    for decision in proposal["decisions"]:
        if decision["action"] == "open":
            decision["theme_id"] = "THEME-0001"
            break


def _append_names_a_placeholder(proposal):
    for decision in proposal["decisions"]:
        if decision["action"] == "append":
            decision["theme_id"] = "NEW-1"
            break


def _section_cites_another_themes_claim(proposal):
    ids = scenario.claims_by_topic()
    section = proposal["digest"]["sections"][0]
    section["evidence_claim_ids"] = [ids["export_row_cap"]]


def _section_cites_an_unknown_claim(proposal):
    proposal["digest"]["sections"][0]["evidence_claim_ids"] = ["bbbbbbbbbbbb"]


def _placeholder_defined_twice(proposal):
    proposal["new_themes"].append(copy.deepcopy(proposal["new_themes"][0]))


@pytest.mark.parametrize(
    "mutation, fragment",
    [
        (_unknown_claim, "not one of this run's verified claims"),
        (_unknown_theme, "not in themes/_INDEX.md"),
        (_undefined_placeholder, "not defined in new_themes"),
        (_claim_decided_twice, "decided more than once"),
        (_claim_never_decided, "was never decided"),
        (_open_names_an_existing_theme, "action open must name a NEW-n placeholder"),
        (_append_names_a_placeholder, "action append must name an existing THEME-nnnn"),
        (_section_cites_another_themes_claim, "was assigned to"),
        (_section_cites_an_unknown_claim, "not one of this run's verified claims"),
        (_placeholder_defined_twice, "defined more than once"),
    ],
)
def test_each_cross_check_bites(store, mutation, fragment):
    index = [dict(line) for line in store.read_theme_index()]
    with pytest.raises(ContractViolation) as excinfo:
        ed.validate_proposal(_mutate(mutation), index, scenario.RUN_CLAIMS,
                             scenario.ENRICHMENT)
    assert any(fragment in error for error in excinfo.value.errors), excinfo.value.errors


def test_a_claim_whose_account_has_no_enrichment_is_a_violation(store):
    index = [dict(line) for line in store.read_theme_index()]
    thin = {k: v for k, v in scenario.ENRICHMENT.items() if k != "ACC-0007"}
    with pytest.raises(ContractViolation) as excinfo:
        ed.validate_proposal(recorded_proposal(), index, scenario.RUN_CLAIMS, thin)
    assert any("no enrichment this run" in error for error in excinfo.value.errors)


def test_a_proposal_that_fails_the_schema_is_rejected_before_any_cross_check(store):
    index = [dict(line) for line in store.read_theme_index()]
    broken = recorded_proposal()
    del broken["digest"]
    with pytest.raises(ContractViolation) as excinfo:
        ed.validate_proposal(broken, index, scenario.RUN_CLAIMS, scenario.ENRICHMENT)
    assert excinfo.value.schema_name == "EditorProposal"


# --------------------------------------------------------------------------- the retry


def test_a_cross_check_failure_retries_once_with_the_violation_appended(store, audit):
    router = StubRouter([
        {"schema_version": "1.0.0", "needs_themes": ["THEME-0001"]},
        _mutate(_unknown_claim),
        recorded_proposal(),
    ])
    proposal = ed.run_editor(scenario.WEEK, scenario.RUN_CLAIMS, scenario.ENRICHMENT,
                             store, router, audit)
    assert len(router.calls) == 3
    retry = router.calls[2]["user"]
    assert "aaaaaaaaaaaa" in retry
    assert "failed schema validation against EditorProposal" in retry
    assert retry.startswith(router.calls[1]["user"])
    assert retry == retry_user_text(
        router.calls[1]["user"], "EditorProposal",
        sorted(["decisions[0].claim_id: aaaaaaaaaaaa is not one of this run's verified claims",
                "decisions: claim %s was never decided; every claim gets exactly one decision"
                % scenario.RUN_CLAIMS[0]["claim_id"],
                "digest.sections[0].evidence_claim_ids: %s was assigned to no theme, not to "
                "NEW-1" % scenario.RUN_CLAIMS[0]["claim_id"]]))
    assert proposal["week"] == scenario.WEEK
    rejects = [e for e in audit.events() if e["action"] == "reject"]
    assert len(rejects) == 1
    assert rejects[0]["detail"]["check"] == "cross_check"


def test_two_cross_check_failures_raise_SchemaRejected_and_patch_nothing(store, audit):
    router = StubRouter([
        {"schema_version": "1.0.0", "needs_themes": []},
        _mutate(_unknown_claim),
        _mutate(_unknown_claim),
    ])
    with pytest.raises(SchemaRejected) as excinfo:
        ed.run_editor(scenario.WEEK, scenario.RUN_CLAIMS, scenario.ENRICHMENT, store,
                      router, audit)
    assert excinfo.value.attempts == 2
    assert excinfo.value.agent == "editor"
    assert excinfo.value.tier == "synthesis"
    assert len(router.calls) == 3
    assert not [e for e in audit.events() if e["action"] == "propose"]


def test_both_calls_ask_for_the_synthesis_tier(store, audit):
    router = StubRouter([
        {"schema_version": "1.0.0", "needs_themes": ["THEME-0001"]},
        recorded_proposal(),
    ])
    ed.run_editor(scenario.WEEK, scenario.RUN_CLAIMS, scenario.ENRICHMENT, store, router,
                  audit)
    assert [c["tier"] for c in router.calls] == ["synthesis", "synthesis"]
    assert [c["schema_name"] for c in router.calls] == ["EditorThemeRequest", "EditorProposal"]
    assert {c["agent"] for c in router.calls} == {"editor"}
    assert {c["stage"] for c in router.calls} == {"edit"}
    assert {c["run_id"] for c in router.calls} == {scenario.RUN_ID}


def test_the_fixture_claim_ids_are_the_contract_hash():
    for claim in scenario.RUN_CLAIMS + scenario.PRIOR_CLAIMS:
        assert claim["claim_id"] == scenario.claim_id(claim["source_ref"], claim["verbatim"])
