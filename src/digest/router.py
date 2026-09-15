"""The model seam. One file to swap platform, one call site for every agent.

Everything a model call needs to be reproducible and explainable lives here: the tier to
model mapping, the capability negotiation, the validate-reject-retry-once rule, the cost
arithmetic, the record and replay corpus, and the audit event per attempt. Nothing else in
the system talks to a provider.

Three modes:

    replay   read the recorded response for the key, zero network, a miss is a hard failure
    record   make the live call, validate, write the recording, return it
    live     make the live call, validate, write nothing, return it

A replay miss never falls back to live. A silent fallback would make a committed demo cost
money, stop being reproducible, and hide the fact that a prompt changed.

The router validates the result against the contract schema in every case, including when
the provider produced it natively. Native structured output is a way to get a better first
try, not a reason to trust the output. Same contract, three implementations, one call site.

This module imports digest.contracts, digest.errors, digest.providers, yaml and the standard
library. It does not import the store, the audit module or any connector, so
`python -c "import digest.router"` works before the rest of the system exists. The audit
object arrives as an argument and is typed as a Protocol for the same reason.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
from typing import Any, Literal, Protocol, TypedDict

import yaml

from digest.contracts import iter_errors, load_schema, validate
from digest.errors import ContractViolation, DigestError, ReplayMiss, SchemaRejected
from digest.providers import Provider, TierParams, get_provider

__all__ = [
    "Router",
    "StructuredResult",
    "Audit",
    "replay_key",
    "prompt_hash",
    "retry_user_text",
    "schema_in_prompt_text",
    "MODES",
    "TIERS",
]

MODES = ("replay", "live", "record")
TIERS = ("extraction", "synthesis", "narrative")

# The stage each tier's work belongs to in the cost table, used when a caller does not name
# one. The fixed stage names live in contracts/file_formats.md section 14.
_TIER_STAGE = {"extraction": "extract", "synthesis": "edit", "narrative": "render"}

_UNIT_SEPARATOR = "\x1f"


class StructuredResult(TypedDict, total=False):
    """One validated model result, plus everything needed to explain what it cost.

    The first twelve keys match RecordedResponse.result exactly. `provider_reported_cost_usd`
    is an extra: the seat CLI reports its own number and comparing the two is how the
    pricing table stays honest. It is deliberately not written to the recording, whose
    schema is closed, and it is None when the provider does not report one.
    """

    data: dict
    model_id: str
    tier: str
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_write: int
    cost_usd: float
    prompt_hash: str
    provider: str
    raw_text: str
    replayed: bool
    provider_reported_cost_usd: float | None


class Audit(Protocol):
    """Whatever digest.audit.Audit turns out to be, this is all the router needs of it."""

    def log(self, **fields: Any) -> dict: ...


def _sha16(parts: list[str]) -> str:
    joined = _UNIT_SEPARATOR.join(parts).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()[:16]


def replay_key(tier: str, system: str, user: str, schema_name: str) -> str:
    """sha256 of tier, system, user and schema_name joined by U+001F, first 16 hex chars."""
    return _sha16([tier, system, user, schema_name])


def prompt_hash(system: str, user: str, schema_name: str) -> str:
    """sha256 of system, user and schema_name joined by U+001F, first 16 hex chars."""
    return _sha16([system, user, schema_name])


def retry_user_text(user: str, schema_name: str, errors: list[str]) -> str:
    """The pinned retry prompt. It is part of a replay key, so the wording cannot drift."""
    lines = "\n".join("- %s" % e for e in errors)
    return (
        "%s\n\n"
        "The previous response failed schema validation against %s.\n"
        "Validation errors:\n"
        "%s\n"
        "Return only a JSON object that satisfies the schema. Do not explain."
        % (user, schema_name, lines)
    )


def schema_in_prompt_text(user: str, schema_name: str, schema: dict) -> str:
    """The third negotiation path: the schema goes in the prompt, code does the enforcing."""
    return (
        "%s\n\n"
        "Return only a JSON object valid against this JSON Schema named %s. "
        "No prose, no code fence.\n"
        "%s"
        % (user, schema_name, json.dumps(schema, sort_keys=True, indent=2))
    )


def _parse_json_object(text: str) -> tuple[dict, list[str]]:
    """Parse model text into an object. Returns (data, errors); errors is empty on success.

    A non object or unparseable response is an empty object plus one error, which is what
    goes into the retry prompt. Nothing is repaired, unwrapped from a code fence, or
    scavenged out of surrounding prose: patching a malformed response is how a pipeline
    starts shipping things nobody validated.
    """
    stripped = (text or "").strip()
    if not stripped:
        return {}, ["$: the model returned an empty response"]
    try:
        doc = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return {}, ["$: the response was not valid JSON: %s" % exc.msg]
    if not isinstance(doc, dict):
        return {}, ["$: the response was a %s, not a JSON object" % type(doc).__name__]
    return doc, []


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Router:
    """Resolve a tier to a model, call it, validate the answer, and account for the cost."""

    def __init__(self, config_path: str | pathlib.Path,
                 mode: Literal["replay", "live", "record"] = "replay",
                 responses_dir: str | pathlib.Path | None = None) -> None:
        if mode not in MODES:
            raise ValueError("mode must be one of %s, got %r" % (", ".join(MODES), mode))
        self.mode = mode
        self.config_path = pathlib.Path(config_path)
        self.config = self._load_config(self.config_path)
        self._responses_dir = pathlib.Path(responses_dir) if responses_dir else None
        self._provider: Provider | None = None

    # -- configuration -----------------------------------------------------------

    @staticmethod
    def _load_config(path: pathlib.Path) -> dict:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractViolation("ModelsConfig", ["$: cannot read %s: %s" % (path, exc)]) from exc
        doc = yaml.safe_load(raw)
        if not isinstance(doc, dict):
            raise ContractViolation("ModelsConfig", ["$: %s did not parse to a mapping" % path])
        validate(doc, "ModelsConfig")
        return doc

    def tiers(self) -> dict[str, dict]:
        return self.config["tiers"]

    def provider_name(self) -> str:
        return self.config["provider"]

    def model_for(self, tier: str) -> str:
        return self._tier(tier)["model"]

    def _tier(self, tier: str) -> dict:
        try:
            return self.config["tiers"][tier]
        except KeyError:
            raise ValueError(
                "unknown tier %r in %s, expected one of: %s"
                % (tier, self.config_path, ", ".join(sorted(self.config["tiers"])))
            ) from None

    def params_for(self, tier: str) -> TierParams:
        block = self._tier(tier)
        return TierParams(
            max_tokens=int(block["max_tokens"]),
            effort=block["effort"],
            thinking_budget=None,       # derived by the adapter from the model family
            temperature=block["temperature"],
        )

    def price(self, model_id: str) -> dict:
        try:
            return self.config["pricing"][model_id]
        except KeyError:
            raise ValueError(
                "no pricing for model %r in %s. Add it rather than guessing: an unpriced "
                "call makes the whole cost table wrong." % (model_id, self.config_path)
            ) from None

    def cost(self, model_id: str, tokens_in: int, tokens_out: int,
             cache_read: int, cache_write: int) -> float:
        """Dollars for one call. tokens_in is non cached input, so the terms never overlap."""
        p = self.price(model_id)
        total = (
            tokens_in * p["input"]
            + tokens_out * p["output"]
            + cache_read * p["cache_read"]
            + cache_write * p["cache_write"]
        ) / 1_000_000
        return round(total, 10)

    # -- provider ----------------------------------------------------------------

    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = get_provider(self.provider_name())
        return self._provider

    def set_provider(self, provider: Provider) -> None:
        """Inject an adapter. The seam the tests use instead of a network."""
        self._provider = provider

    def negotiate(self, provider: Provider | None = None) -> str:
        """Pick the strongest structured output path the adapter declares.

        Order is fixed: native structured output, then a strict tool, then the schema in
        the prompt. All three end at the same place because the router validates the
        result against the contract either way.
        """
        caps = (provider or self.provider()).capabilities()
        if caps.get("native_structured"):
            return "native_structured"
        if caps.get("strict_tools"):
            return "strict_tool"
        return "schema_in_prompt"

    # -- recordings --------------------------------------------------------------

    def responses_dir(self, run_id: str) -> pathlib.Path:
        """Where recordings live.

        Explicit argument first, then DIGEST_RESPONSES_DIR, then
        <store>/runs/<run_id>/responses with the store taken from DIGEST_STORE_PATH and
        falling back to the sibling store repository. The store module is not imported
        here on purpose; the router has to be importable before it exists.
        """
        if self._responses_dir is not None:
            return self._responses_dir
        env_dir = os.environ.get("DIGEST_RESPONSES_DIR")
        if env_dir:
            return pathlib.Path(env_dir)
        store = os.environ.get("DIGEST_STORE_PATH")
        root = pathlib.Path(store) if store else (
            pathlib.Path(__file__).resolve().parents[3] / "bi-theme-digest-store"
        )
        return root / "runs" / run_id / "responses"

    # -- the one entry point -----------------------------------------------------

    def complete(self, tier: str, system: str, user: str, schema_name: str, *,
                 run_id: str, agent: str, audit: Audit,
                 stage: str | None = None) -> StructuredResult:
        """Call the model for `tier`, validate against `schema_name`, retry once, then fail.

        A first try success writes call_model then validate. A retry success writes
        call_model, call_model, validate. A final failure writes call_model, call_model,
        reject and raises SchemaRejected. Nothing is patched and nothing is coerced.

        `stage` is not in the published signature because a caller usually has exactly one,
        so it defaults from the tier. Pass it when the caller's stage differs.
        """
        model_id = self.model_for(tier)
        stage = stage or _TIER_STAGE.get(tier, "extract")
        hashed = prompt_hash(system, user, schema_name)

        result, data, errors = self._attempt(
            attempt=1, tier=tier, system=system, user=user, schema_name=schema_name,
            model_id=model_id, prompt_hash_value=hashed, run_id=run_id, agent=agent,
            audit=audit, stage=stage,
        )
        if not errors:
            self._log_validate(audit, agent, stage, schema_name, result, attempt=1)
            return result

        retry_user = retry_user_text(user, schema_name, errors)
        result2, data2, errors2 = self._attempt(
            attempt=2, tier=tier, system=system, user=retry_user, schema_name=schema_name,
            model_id=model_id, prompt_hash_value=hashed, run_id=run_id, agent=agent,
            audit=audit, stage=stage,
        )
        if not errors2:
            self._log_validate(audit, agent, stage, schema_name, result2, attempt=2)
            return result2

        audit.log(agent=agent, action="reject", stage=stage, target=schema_name,
                  model_tier=tier, model_id=model_id, prompt_hash=hashed,
                  outcome="rejected",
                  detail={"attempts": 2, "errors": errors2, "first_attempt_errors": errors})
        raise SchemaRejected(schema_name, errors2, attempts=2, agent=agent, tier=tier)

    # -- one attempt -------------------------------------------------------------

    def _attempt(self, *, attempt: int, tier: str, system: str, user: str, schema_name: str,
                 model_id: str, prompt_hash_value: str, run_id: str, agent: str,
                 audit: Audit, stage: str) -> tuple[StructuredResult, dict, list[str]]:
        key = replay_key(tier, system, user, schema_name)
        if self.mode == "replay":
            result = self._replay(key, tier, agent, run_id, model_id)
        else:
            result = self._live(key, tier, system, user, schema_name, model_id,
                                prompt_hash_value, attempt, agent, run_id, audit, stage)

        data, parse_errors = _parse_json_object(result["raw_text"])
        result["data"] = data
        errors = parse_errors or iter_errors(data, schema_name)

        audit.log(agent=agent, action="call_model", stage=stage, target=schema_name,
                  model_tier=tier, model_id=result["model_id"], prompt_hash=prompt_hash_value,
                  tokens_in=result["tokens_in"], tokens_out=result["tokens_out"],
                  cache_read=result["cache_read"], cache_write=result["cache_write"],
                  cost_usd=result["cost_usd"], outcome="ok",
                  detail=self._call_detail(result, attempt, key, errors))
        return result, data, errors

    def _call_detail(self, result: StructuredResult, attempt: int, key: str,
                     errors: list[str]) -> dict:
        detail: dict[str, Any] = {
            "attempt": attempt,
            "replayed": result["replayed"],
            "key": key,
            "path": result.get("path", "native_structured"),
            "valid": not errors,
        }
        dropped = result.get("dropped_params")
        if dropped:
            detail["dropped_params"] = list(dropped)
        reported = result.get("provider_reported_cost_usd")
        if reported is not None:
            detail["provider_reported_cost_usd"] = reported
        return detail

    def _replay(self, key: str, tier: str, agent: str, run_id: str,
                model_id: str) -> StructuredResult:
        directory = self.responses_dir(run_id)
        path = directory / ("%s.json" % key)
        if not path.is_file():
            raise ReplayMiss(key, tier, agent, str(directory))
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractViolation("RecordedResponse",
                                    ["$: cannot read %s: %s" % (path, exc)]) from exc
        validate(doc, "RecordedResponse")
        result: StructuredResult = dict(doc["result"])  # type: ignore[assignment]
        result["replayed"] = True
        result.setdefault("provider_reported_cost_usd", None)
        result["path"] = "replay"
        return result

    def _live(self, key: str, tier: str, system: str, user: str, schema_name: str,
              model_id: str, prompt_hash_value: str, attempt: int, agent: str,
              run_id: str, audit: Audit, stage: str) -> StructuredResult:
        provider = self.provider()
        path = self.negotiate(provider)
        schema = load_schema(schema_name)
        sent_user = user
        if path == "schema_in_prompt":
            sent_user = schema_in_prompt_text(user, schema_name, schema)

        params = self.params_for(tier)
        translated = provider.translate_model_id(model_id)
        try:
            raw = provider.complete(translated, system, sent_user, schema, params)
        except Exception as exc:  # noqa: BLE001 - logged, then raised on to the caller
            audit.log(agent=agent, action="call_model", stage=stage, target=schema_name,
                      model_tier=tier, model_id=model_id, prompt_hash=prompt_hash_value,
                      outcome="error",
                      detail={"attempt": attempt, "key": key, "path": path,
                              "provider": provider.name, "exception": type(exc).__name__})
            if isinstance(exc, DigestError):
                raise
            raise DigestError("%s: %s" % (provider.name, exc)) from exc

        result = StructuredResult(
            data={},
            model_id=model_id,
            tier=tier,
            tokens_in=int(raw.get("tokens_in", 0)),
            tokens_out=int(raw.get("tokens_out", 0)),
            cache_read=int(raw.get("cache_read", 0)),
            cache_write=int(raw.get("cache_write", 0)),
            cost_usd=0.0,
            prompt_hash=prompt_hash_value,
            provider=provider.name,
            raw_text=raw.get("text", ""),
            replayed=False,
            provider_reported_cost_usd=raw.get("provider_reported_cost_usd"),
        )
        result["cost_usd"] = self.cost(model_id, result["tokens_in"], result["tokens_out"],
                                       result["cache_read"], result["cache_write"])
        result["path"] = path
        if raw.get("dropped_params"):
            result["dropped_params"] = list(raw["dropped_params"])

        if self.mode == "record":
            self._write_recording(key, tier, agent, schema_name, system, user, attempt,
                                  result, run_id)
        return result

    def _write_recording(self, key: str, tier: str, agent: str, schema_name: str,
                         system: str, user: str, attempt: int, result: StructuredResult,
                         run_id: str) -> pathlib.Path:
        """Write one recording. Every attempt gets a file, including a failed one.

        A failed first attempt has its own key because its user text is the original, and
        the retry has another because its user text carries the errors. Recording both is
        what lets a rejection replay as a rejection instead of turning into a replay miss
        halfway through the sequence.
        """
        data, _ = _parse_json_object(result["raw_text"])
        stored: dict[str, Any] = {
            "data": data,
            "model_id": result["model_id"],
            "tier": result["tier"],
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
            "cache_read": result["cache_read"],
            "cache_write": result["cache_write"],
            "cost_usd": result["cost_usd"],
            "prompt_hash": result["prompt_hash"],
            "provider": result["provider"],
            "raw_text": result["raw_text"],
            "replayed": False,
        }
        doc = {
            "schema_version": "1.0.0",
            "key": key,
            "recorded_at": _now(),
            "request": {
                "tier": tier,
                "agent": agent,
                "schema_name": schema_name,
                "system": system,
                "user": user,
                "attempt": attempt,
            },
            "result": stored,
        }
        validate(doc, "RecordedResponse")
        directory = self.responses_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("%s.json" % key)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _log_validate(audit: Audit, agent: str, stage: str, schema_name: str,
                      result: StructuredResult, attempt: int) -> None:
        audit.log(agent=agent, action="validate", stage=stage, target=schema_name,
                  model_tier=result["tier"], model_id=result["model_id"],
                  prompt_hash=result["prompt_hash"], outcome="ok",
                  detail={"attempt": attempt, "replayed": result["replayed"]})
