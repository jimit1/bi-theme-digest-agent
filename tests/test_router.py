"""The router and the provider adapters.

What is asserted here is the part of the system that decides what a call costs, whether its
answer is allowed through, and whether the same input gives the same answer tomorrow. So:
tier lookup, the cost arithmetic against the contract's own worked example, the negotiation
order across all six adapters, validate-reject-retry-once with a provider that returns
rubbish twice, replay hit and replay miss, record writing a file, the request body the
direct adapter builds for each of the four model families, and the model id each stub
translates to.

Two of the fixtures under tests/fixtures/b5 came from live calls on a Claude seat. The
recorded responses replay through the router with zero network, and the raw CLI payload
replays through the seat adapter's own parser, so the code that reads a live result is the
code under test rather than a mock of it.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from digest.contracts import load_schema, validate  # noqa: E402
from digest.errors import ContractViolation, DigestError, ReplayMiss, SchemaRejected  # noqa: E402
from digest.providers import PROVIDER_NAMES, TierParams, get_provider  # noqa: E402
from digest.providers._families import family_for, thinking_budget_for  # noqa: E402
from digest.providers.agent_sdk_seat import AgentSdkSeatProvider, transport_schema  # noqa: E402
from digest.providers.anthropic_direct import AnthropicDirectProvider  # noqa: E402
from digest.router import (  # noqa: E402
    Router,
    prompt_hash,
    replay_key,
    retry_user_text,
)

CONFIG = REPO / "config" / "models.yaml"
CHEAP = REPO / "config" / "models.cheap.yaml"
FIXTURES = REPO / "tests" / "fixtures" / "b5"
RUN_ID = "2026-09-14T07:00Z"

SYSTEM = "You are a test."
USER = "Return the empty list."
SCHEMA_NAME = "EditorThemeRequest"
GOOD = json.dumps({"schema_version": "1.0.0", "needs_themes": []})


# ---------------------------------------------------------------- fakes


class FakeAudit:
    """Stands in for digest.audit.Audit and holds the log to the same contract.

    Every event the router emits is stamped and validated against AuditEvent here, so a
    router that logs a field the schema does not allow fails this file rather than the
    integration.
    """

    def __init__(self, run_id: str = RUN_ID) -> None:
        self.run_id = run_id
        self.events: list[dict] = []

    def log(self, **fields) -> dict:
        event = {
            "schema_version": "1.0.0",
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "run_id": self.run_id,
            "model_tier": None,
            "model_id": None,
            "prompt_hash": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "cache_read": 0,
            "cache_write": 0,
            "cost_usd": 0.0,
            "outcome": "ok",
            "detail": {},
        }
        event.update(fields)
        validate(event, "AuditEvent")
        self.events.append(event)
        return event

    def actions(self) -> list[str]:
        return [e["action"] for e in self.events]


class FakeProvider:
    """A provider that returns whatever the test queued, and remembers what it was asked."""

    def __init__(self, name: str = "fake", texts=(GOOD,), native: bool = True,
                 strict: bool = False, raises: BaseException | None = None) -> None:
        self.name = name
        self._texts = list(texts)
        self._native = native
        self._strict = strict
        self._raises = raises
        self.calls: list[dict] = []

    def capabilities(self):
        return {"native_structured": self._native, "strict_tools": self._strict,
                "thinking_style": "adaptive", "effort": True}

    def translate_model_id(self, canonical_model_id: str) -> str:
        return canonical_model_id

    def complete(self, model_id, system, user, schema, params):
        self.calls.append({"model_id": model_id, "system": system, "user": user,
                           "schema": schema, "params": params})
        if self._raises is not None:
            raise self._raises
        text = self._texts[min(len(self.calls), len(self._texts)) - 1]
        return {"text": text, "tokens_in": 100, "tokens_out": 20, "cache_read": 0,
                "cache_write": 0, "stop_reason": "end_turn", "dropped_params": [],
                "provider_reported_cost_usd": 0.000123}


def router_with(provider, mode="live", responses_dir=None, config=CONFIG) -> Router:
    router = Router(config, mode=mode, responses_dir=responses_dir)
    router.set_provider(provider)
    return router


# ---------------------------------------------------------------- config and tiers


def test_config_validates_and_tiers_resolve():
    router = Router(CONFIG)
    assert sorted(router.tiers()) == ["extraction", "narrative", "synthesis"]
    assert router.model_for("extraction") != router.model_for("synthesis")
    assert router.model_for("narrative") == router.model_for("synthesis")
    assert router.provider_name() in PROVIDER_NAMES
    params = router.params_for("extraction")
    assert params["max_tokens"] == 4000
    assert params["effort"] == "low"


def test_cheap_config_puts_every_tier_on_one_model():
    cheap = Router(CHEAP)
    models = {cheap.model_for(t) for t in cheap.tiers()}
    assert len(models) == 1
    assert models == {Router(CONFIG).model_for("extraction")}
    assert all(cheap.tiers()[t]["effort"] is None for t in cheap.tiers())


def test_unknown_tier_and_unknown_mode_are_loud():
    with pytest.raises(ValueError):
        Router(CONFIG).model_for("summarisation")
    with pytest.raises(ValueError):
        Router(CONFIG, mode="cheat")


def test_a_config_that_does_not_validate_raises_contract_violation(tmp_path):
    bad = tmp_path / "models.yaml"
    bad.write_text("schema_version: '1.0.0'\nprovider: agent_sdk_seat\n", encoding="utf-8")
    with pytest.raises(ContractViolation):
        Router(bad)


# ---------------------------------------------------------------- cost


def test_cost_matches_the_contract_worked_example():
    """The RecordedResponse example carries tokens and a cost. Recompute it exactly."""
    example = json.loads((REPO / "contracts" / "examples"
                          / "RecordedResponse.example.json").read_text(encoding="utf-8"))
    r = example["result"]
    router = Router(CONFIG)
    assert router.cost(r["model_id"], r["tokens_in"], r["tokens_out"],
                       r["cache_read"], r["cache_write"]) == r["cost_usd"]


def test_cost_counts_all_four_token_buckets_separately():
    router = Router(CONFIG)
    model = router.model_for("synthesis")
    price = router.price(model)
    assert router.cost(model, 1_000_000, 0, 0, 0) == pytest.approx(price["input"])
    assert router.cost(model, 0, 1_000_000, 0, 0) == pytest.approx(price["output"])
    assert router.cost(model, 0, 0, 1_000_000, 0) == pytest.approx(price["cache_read"])
    assert router.cost(model, 0, 0, 0, 1_000_000) == pytest.approx(price["cache_write"])
    assert price["cache_read"] == pytest.approx(price["input"] * 0.1)
    assert price["cache_write"] == pytest.approx(price["input"] * 1.25)


def test_an_unpriced_model_refuses_to_guess():
    with pytest.raises(ValueError):
        Router(CONFIG).price("a-model-nobody-configured")


# ---------------------------------------------------------------- keys


def test_replay_key_and_prompt_hash_match_the_contract_example():
    example = json.loads((REPO / "contracts" / "examples"
                          / "RecordedResponse.example.json").read_text(encoding="utf-8"))
    req = example["request"]
    assert replay_key(req["tier"], req["system"], req["user"],
                      req["schema_name"]) == example["key"]
    assert prompt_hash(req["system"], req["user"],
                       req["schema_name"]) == example["result"]["prompt_hash"]


def test_the_retry_prompt_is_pinned_word_for_word():
    text = retry_user_text("ORIGINAL", "Theme", ["$.a: one", "$.b: two"])
    assert text == (
        "ORIGINAL\n\n"
        "The previous response failed schema validation against Theme.\n"
        "Validation errors:\n"
        "- $.a: one\n"
        "- $.b: two\n"
        "Return only a JSON object that satisfies the schema. Do not explain."
    )


# ---------------------------------------------------------------- negotiation


def test_negotiation_order_across_every_adapter():
    expected = {
        "agent_sdk_seat": "native_structured",
        "anthropic_direct": "native_structured",
        "bedrock": "strict_tool",
        "vertex": "strict_tool",
        "foundry": "strict_tool",
        "openai_compatible": "schema_in_prompt",
    }
    router = Router(CONFIG)
    for name, path in expected.items():
        assert router.negotiate(get_provider(name)) == path, name


def test_native_beats_strict_and_strict_beats_prompt():
    router = Router(CONFIG)
    assert router.negotiate(FakeProvider(native=True, strict=True)) == "native_structured"
    assert router.negotiate(FakeProvider(native=False, strict=True)) == "strict_tool"
    assert router.negotiate(FakeProvider(native=False, strict=False)) == "schema_in_prompt"


def test_the_prompt_path_puts_the_schema_in_the_user_text():
    provider = FakeProvider(native=False, strict=False)
    router = router_with(provider)
    router.complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                    run_id=RUN_ID, agent="editor", audit=FakeAudit())
    sent = provider.calls[0]["user"]
    assert USER in sent
    assert '"needs_themes"' in sent
    assert "additionalProperties" in sent


def test_native_output_is_still_validated_in_code():
    """Native structured output is a better first try, not a reason to trust the answer."""
    provider = FakeProvider(native=True, texts=[json.dumps({"schema_version": "9.9.9"})] * 2)
    router = router_with(provider)
    with pytest.raises(SchemaRejected):
        router.complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                        run_id=RUN_ID, agent="editor", audit=FakeAudit())


# ---------------------------------------------------------------- validate, retry, reject


def test_first_try_success_logs_call_model_then_validate():
    audit = FakeAudit()
    provider = FakeProvider(texts=[GOOD])
    result = router_with(provider).complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                                            run_id=RUN_ID, agent="editor", audit=audit)
    assert audit.actions() == ["call_model", "validate"]
    assert result["data"] == {"schema_version": "1.0.0", "needs_themes": []}
    assert result["replayed"] is False
    assert result["cost_usd"] == pytest.approx(0.0002)
    assert result["provider_reported_cost_usd"] == 0.000123
    assert len(provider.calls) == 1


def test_retry_once_and_succeed_on_the_second_attempt():
    audit = FakeAudit()
    provider = FakeProvider(texts=["not json at all", GOOD])
    result = router_with(provider).complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                                            run_id=RUN_ID, agent="editor", audit=audit)
    assert audit.actions() == ["call_model", "call_model", "validate"]
    assert result["data"]["needs_themes"] == []
    second = provider.calls[1]["user"]
    assert second.startswith(USER)
    assert "failed schema validation against EditorThemeRequest" in second


def test_two_bad_responses_are_rejected_and_never_patched():
    audit = FakeAudit()
    provider = FakeProvider(texts=["{not json", "{still not json"])
    with pytest.raises(SchemaRejected) as caught:
        router_with(provider).complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                                       run_id=RUN_ID, agent="editor", audit=audit)
    assert caught.value.attempts == 2
    assert caught.value.agent == "editor"
    assert caught.value.tier == "extraction"
    assert caught.value.exit_code == 2
    assert audit.actions() == ["call_model", "call_model", "reject"]
    reject = audit.events[-1]
    assert reject["outcome"] == "rejected"
    assert reject["detail"]["errors"]
    assert len(provider.calls) == 2, "exactly one retry, never two"


def test_valid_json_of_the_wrong_shape_is_rejected_too():
    audit = FakeAudit()
    wrong = json.dumps({"schema_version": "1.0.0", "needs_themes": ["not-a-theme-id"]})
    with pytest.raises(SchemaRejected):
        router_with(FakeProvider(texts=[wrong, wrong])).complete(
            "extraction", SYSTEM, USER, SCHEMA_NAME,
            run_id=RUN_ID, agent="editor", audit=audit)
    assert audit.actions() == ["call_model", "call_model", "reject"]


def test_a_provider_error_is_logged_as_an_error_and_raised():
    audit = FakeAudit()
    provider = FakeProvider(raises=DigestError("boom"))
    with pytest.raises(DigestError):
        router_with(provider).complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                                       run_id=RUN_ID, agent="editor", audit=audit)
    assert audit.actions() == ["call_model"]
    assert audit.events[0]["outcome"] == "error"


# ---------------------------------------------------------------- record and replay


def test_record_writes_one_file_per_attempt(tmp_path):
    provider = FakeProvider(texts=["not json", GOOD])
    router = router_with(provider, mode="record", responses_dir=tmp_path)
    router.complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                    run_id=RUN_ID, agent="editor", audit=FakeAudit())
    written = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(written) == 2, "the failed attempt and the retry each get their own key"
    first = tmp_path / ("%s.json" % replay_key("extraction", SYSTEM, USER, SCHEMA_NAME))
    assert first.is_file()
    doc = json.loads(first.read_text(encoding="utf-8"))
    validate(doc, "RecordedResponse")
    assert doc["request"]["attempt"] == 1
    assert doc["result"]["replayed"] is False


def test_live_mode_writes_nothing(tmp_path):
    router = router_with(FakeProvider(texts=[GOOD]), mode="live", responses_dir=tmp_path)
    router.complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                    run_id=RUN_ID, agent="editor", audit=FakeAudit())
    assert list(tmp_path.glob("*.json")) == []


def test_a_recording_replays_with_no_provider_at_all(tmp_path):
    router = router_with(FakeProvider(texts=[GOOD]), mode="record", responses_dir=tmp_path)
    router.complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                    run_id=RUN_ID, agent="editor", audit=FakeAudit())

    audit = FakeAudit()
    replayer = Router(CONFIG, mode="replay", responses_dir=tmp_path)
    replayer.set_provider(FakeProvider(raises=AssertionError("replay must not call out")))
    result = replayer.complete("extraction", SYSTEM, USER, SCHEMA_NAME,
                               run_id=RUN_ID, agent="editor", audit=audit)
    assert result["replayed"] is True
    assert result["data"] == {"schema_version": "1.0.0", "needs_themes": []}
    assert audit.actions() == ["call_model", "validate"]
    assert audit.events[0]["detail"]["replayed"] is True


def test_a_replay_miss_is_fatal_and_never_falls_back_to_live(tmp_path):
    router = Router(CONFIG, mode="replay", responses_dir=tmp_path)
    router.set_provider(FakeProvider(raises=AssertionError("replay must not call out")))
    with pytest.raises(ReplayMiss) as caught:
        router.complete("extraction", SYSTEM, "a prompt nobody recorded", SCHEMA_NAME,
                        run_id=RUN_ID, agent="editor", audit=FakeAudit())
    assert caught.value.exit_code == 3
    assert caught.value.tier == "extraction"
    assert str(tmp_path) in str(caught.value)


def test_a_changed_prompt_changes_the_key(tmp_path):
    a = replay_key("extraction", SYSTEM, USER, SCHEMA_NAME)
    b = replay_key("extraction", SYSTEM, USER + " ", SCHEMA_NAME)
    c = replay_key("synthesis", SYSTEM, USER, SCHEMA_NAME)
    assert len({a, b, c}) == 3


# ---------------------------------------------------------------- the live recordings


def _recorded_requests() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((FIXTURES / "responses").glob("*.json"))]


def test_the_live_seat_recordings_replay_through_the_router():
    """These two files came from real calls on a Claude seat. They replay with no network."""
    docs = _recorded_requests()
    assert len(docs) >= 2
    router = Router(CONFIG, mode="replay", responses_dir=FIXTURES / "responses")
    router.set_provider(FakeProvider(raises=AssertionError("replay must not call out")))
    for doc in docs:
        req = doc["request"]
        audit = FakeAudit()
        result = router.complete(req["tier"], req["system"], req["user"], req["schema_name"],
                                 run_id=RUN_ID, agent=req["agent"], audit=audit)
        assert result["replayed"] is True
        assert result["provider"] == "agent_sdk_seat"
        assert result["tokens_out"] > 0
        assert audit.actions() == ["call_model", "validate"]
        validate(result["data"], req["schema_name"])


def test_the_recorded_key_is_the_key_the_router_computes():
    for doc in _recorded_requests():
        req = doc["request"]
        assert replay_key(req["tier"], req["system"], req["user"],
                          req["schema_name"]) == doc["key"]


def test_the_recorded_cost_matches_the_pricing_table():
    router = Router(CONFIG)
    for doc in _recorded_requests():
        r = doc["result"]
        assert router.cost(r["model_id"], r["tokens_in"], r["tokens_out"],
                           r["cache_read"], r["cache_write"]) == r["cost_usd"]


# ---------------------------------------------------------------- the seat adapter


def test_the_seat_command_line_carries_every_flag_that_matters():
    provider = AgentSdkSeatProvider(cli_path="/bin/claude", bare=False)
    schema = load_schema(SCHEMA_NAME)
    params = TierParams(max_tokens=4000, effort="high", thinking_budget=None, temperature=0)
    argv, dropped = provider.build_argv("a-haiku-4-5-model", SYSTEM, USER, schema, params)
    assert argv[0] == "/bin/claude"
    assert argv[1:3] == ["-p", USER]
    for flag in ("--model", "--output-format", "--json-schema", "--system-prompt",
                 "--tools", "--no-session-persistence"):
        assert flag in argv, flag
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--tools") + 1] == ""
    sent = json.loads(argv[argv.index("--json-schema") + 1])
    assert sent["additionalProperties"] is False
    assert sent["required"] == schema["required"]
    assert "$schema" not in sent and "$id" not in sent
    assert "--effort" not in argv, "this family rejects effort"
    assert dropped == ["effort", "temperature"]


def test_the_seat_adapter_passes_effort_for_a_family_that_takes_it():
    provider = AgentSdkSeatProvider(cli_path="/bin/claude", bare=False)
    params = TierParams(max_tokens=8000, effort="high", thinking_budget=None, temperature=None)
    argv, dropped = provider.build_argv("an-opus-5-model", SYSTEM, USER,
                                        load_schema(SCHEMA_NAME), params)
    assert argv[argv.index("--effort") + 1] == "high"
    assert dropped == []


def test_bare_and_setting_sources_are_alternatives():
    schema = load_schema(SCHEMA_NAME)
    params = TierParams(max_tokens=4000, effort=None, thinking_budget=None, temperature=None)
    bare, _ = AgentSdkSeatProvider(cli_path="c", bare=True).build_argv(
        "m", SYSTEM, USER, schema, params)
    sourced, _ = AgentSdkSeatProvider(cli_path="c", bare=False).build_argv(
        "m", SYSTEM, USER, schema, params)
    assert "--bare" in bare and "--setting-sources" not in bare
    assert "--bare" not in sourced and sourced[sourced.index("--setting-sources") + 1] == ""


def test_transport_schema_drops_only_metadata():
    schema = load_schema(SCHEMA_NAME)
    sent = transport_schema(schema)
    assert set(schema) - set(sent) == {"$schema", "$id"}
    assert sent["properties"] == schema["properties"]


def test_the_seat_adapter_parses_a_real_recorded_cli_payload():
    payload = json.loads((FIXTURES / "cli" / "answer_ok.json").read_text(encoding="utf-8"))
    provider = AgentSdkSeatProvider(cli_path="c")
    result = provider.parse_result(0, json.dumps(payload), "", ["effort"])
    usage = payload["usage"]
    assert json.loads(result["text"]) == payload["structured_output"]
    assert result["tokens_in"] == usage["input_tokens"]
    assert result["tokens_out"] == usage["output_tokens"]
    assert result["cache_read"] == usage["cache_read_input_tokens"]
    assert result["cache_write"] == usage["cache_creation_input_tokens"]
    assert result["provider_reported_cost_usd"] == payload["total_cost_usd"]
    assert result["dropped_params"] == ["effort"]


def test_the_seat_adapter_treats_is_error_and_a_nonzero_exit_as_failures():
    provider = AgentSdkSeatProvider(cli_path="c")
    failed = json.dumps({"is_error": True, "result": "Not logged in", "usage": {}})
    with pytest.raises(DigestError):
        provider.parse_result(0, failed, "")
    with pytest.raises(DigestError):
        provider.parse_result(1, json.dumps({"is_error": False, "usage": {}}), "")
    with pytest.raises(DigestError):
        provider.parse_result(0, "", "segfault")


def test_the_seat_adapter_reports_a_timeout_rather_than_hanging():
    def boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    provider = AgentSdkSeatProvider(cli_path="c", runner=boom, timeout=1)
    params = TierParams(max_tokens=4000, effort=None, thinking_budget=None, temperature=None)
    with pytest.raises(DigestError, match="timed out"):
        provider.complete("m", SYSTEM, USER, load_schema(SCHEMA_NAME), params)


# ---------------------------------------------------------------- the direct adapter


class FakeMessages:
    def __init__(self, text: str = GOOD) -> None:
        self.text = text
        self.seen: dict | None = None

    def create(self, **kwargs):
        self.seen = kwargs
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": self.text}],
            "usage": {"input_tokens": 11, "output_tokens": 22,
                      "cache_read_input_tokens": 33, "cache_creation_input_tokens": 44},
        }


class FakeClient:
    def __init__(self, text: str = GOOD) -> None:
        self.messages = FakeMessages(text)


@pytest.mark.parametrize("model_id, expect_thinking, expect_effort", [
    ("a-haiku-4-5-model", "budget", False),
    ("an-opus-5-model", "adaptive", True),
    ("an-opus-4-6-model", "adaptive", True),
    ("a-fable-5-1-model", None, True),
])
def test_the_direct_adapter_builds_the_right_body_per_family(model_id, expect_thinking,
                                                             expect_effort):
    provider = AnthropicDirectProvider(client=FakeClient())
    params = TierParams(max_tokens=8000, effort="high", thinking_budget=None, temperature=0.3)
    body, dropped = provider.build_request(model_id, SYSTEM, USER,
                                           load_schema(SCHEMA_NAME), params)
    assert body["model"] == model_id
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "temperature" not in body, "thinking is active, so temperature is dropped"
    assert "temperature" in dropped

    if expect_thinking == "budget":
        assert body["thinking"] == {"type": "enabled",
                                    "budget_tokens": thinking_budget_for(8000)}
        assert 1024 <= body["thinking"]["budget_tokens"] < body["max_tokens"]
    elif expect_thinking == "adaptive":
        assert body["thinking"] == {"type": "adaptive"}
    else:
        assert "thinking" not in body

    if expect_effort:
        assert body["output_config"]["effort"] in ("high",)
    else:
        assert "effort" not in body["output_config"]
        assert "effort" in dropped


def test_the_direct_adapter_clamps_an_effort_the_family_will_not_take():
    provider = AnthropicDirectProvider(client=FakeClient())
    params = TierParams(max_tokens=8000, effort="max", thinking_budget=None, temperature=None)
    body, dropped = provider.build_request("an-opus-4-6-model", SYSTEM, USER,
                                           load_schema(SCHEMA_NAME), params)
    assert body["output_config"]["effort"] == "high"
    assert dropped == ["effort:max->high"]


def test_the_direct_adapter_streams_a_long_turn():
    provider = AnthropicDirectProvider(client=FakeClient())
    params = TierParams(max_tokens=32000, effort=None, thinking_budget=None, temperature=None)
    body, _ = provider.build_request("an-opus-5-model", SYSTEM, USER,
                                     load_schema(SCHEMA_NAME), params)
    assert body["stream"] is True
    short, _ = provider.build_request("an-opus-5-model", SYSTEM, USER,
                                      load_schema(SCHEMA_NAME),
                                      TierParams(max_tokens=16000, effort=None,
                                                 thinking_budget=None, temperature=None))
    assert "stream" not in short


def test_the_direct_adapter_maps_usage_and_is_driven_by_the_router():
    client = FakeClient()
    provider = AnthropicDirectProvider(client=client)
    router = router_with(provider)
    result = router.complete("synthesis", SYSTEM, USER, SCHEMA_NAME,
                             run_id=RUN_ID, agent="editor", audit=FakeAudit())
    assert result["tokens_in"] == 11 and result["tokens_out"] == 22
    assert result["cache_read"] == 33 and result["cache_write"] == 44
    assert result["provider"] == "anthropic_direct"
    assert client.messages.seen["messages"] == [{"role": "user", "content": USER}]


def test_the_direct_adapter_surfaces_a_refusal():
    client = FakeClient()
    client.messages.create = lambda **kw: {"stop_reason": "refusal", "content": [], "usage": {}}
    provider = AnthropicDirectProvider(client=client)
    params = TierParams(max_tokens=4000, effort=None, thinking_budget=None, temperature=None)
    with pytest.raises(DigestError, match="refused"):
        provider.complete("an-opus-5-model", SYSTEM, USER, load_schema(SCHEMA_NAME), params)


# ---------------------------------------------------------------- families


def test_family_detection_survives_a_platform_prefix_and_an_at_separator():
    assert family_for("anthropic.a-haiku-4-5-model").thinking_style == "budget"
    assert family_for("us.anthropic.an-opus-5-model").thinking_style == "adaptive"
    assert family_for("an-opus-4-6-model@20260115").explicit_adaptive is True
    assert family_for("something-nobody-has-heard-of").thinking_style == "none"


def test_the_thinking_budget_is_pinned():
    assert thinking_budget_for(4000) == 2000
    assert thinking_budget_for(2000) == 1024
    assert thinking_budget_for(1500) == 1024
    assert thinking_budget_for(1024) == 1023


# ---------------------------------------------------------------- the stubs


@pytest.mark.parametrize("name", ["bedrock", "vertex", "foundry", "openai_compatible"])
def test_every_stub_declares_itself_and_refuses_to_pretend(name):
    provider = get_provider(name)
    assert provider.name == name
    caps = provider.capabilities()
    assert set(caps) == {"native_structured", "strict_tools", "thinking_style", "effort"}
    params = TierParams(max_tokens=4000, effort=None, thinking_budget=None, temperature=None)
    with pytest.raises(NotImplementedError, match="^stub: "):
        provider.complete("m", SYSTEM, USER, load_schema(SCHEMA_NAME), params)


def test_bedrock_prefixes_the_vendor_and_optionally_the_region_group():
    plain = get_provider("bedrock")
    assert plain.translate_model_id("some-model") == "anthropic.some-model"
    assert plain.translate_model_id("anthropic.some-model") == "anthropic.some-model"
    cross = get_provider("bedrock", cross_region=True)
    assert cross.translate_model_id("some-model") == "us.anthropic.some-model"


def test_vertex_swaps_the_version_separator_for_an_at_sign():
    vertex = get_provider("vertex")
    assert vertex.translate_model_id("some-model-20260115") == "some-model@20260115"
    assert vertex.translate_model_id("some-model") == "some-model"
    assert vertex.translate_model_id("some-model@20260115") == "some-model@20260115"


def test_foundry_uses_a_deployment_name_and_falls_back_to_the_canonical_id():
    assert get_provider("foundry").translate_model_id("some-model") == "some-model"
    assert get_provider("foundry", deployment="prod-a").translate_model_id("m") == "prod-a"
    mapped = get_provider("foundry", deployments={"m": "prod-b"}, deployment="prod-a")
    assert mapped.translate_model_id("m") == "prod-b"
    assert mapped.translate_model_id("other") == "prod-a"


def test_an_openai_compatible_gateway_passes_the_id_through_unless_mapped():
    assert get_provider("openai_compatible").translate_model_id("m") == "m"
    mapped = get_provider("openai_compatible", model_map={"m": "gateway-m"})
    assert mapped.translate_model_id("m") == "gateway-m"


def test_an_unknown_provider_name_is_a_value_error_not_a_default():
    with pytest.raises(ValueError, match="unknown provider"):
        get_provider("telepathy")


# ---------------------------------------------------------------- the grep


def test_no_model_id_appears_anywhere_under_src():
    """config/models.yaml is the only runtime file allowed to name a model."""
    hits = []
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "claude-" in line:
                hits.append("%s:%d: %s" % (path.relative_to(REPO), number, line.strip()))
    assert hits == [], "model ids belong in config, not in code:\n" + "\n".join(hits)


def test_the_router_imports_without_the_rest_of_the_system():
    out = subprocess.run([sys.executable, "-c", "import digest.router"],
                         capture_output=True, text=True,
                         env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
