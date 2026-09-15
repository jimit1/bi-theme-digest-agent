"""The Anthropic direct adapter: the `anthropic` package against the public API.

Works, but it is not exercised live here because ANTHROPIC_API_KEY is unset on this
machine. The tests inject a fake client and assert on the request body, which is the part
that differs per model family and the part that returns a 400 when it is wrong.

Everything family specific is read from digest.providers._families, so this adapter and any
future one compute the same thinking budget and drop the same parameters. What that means in
practice, per family:

    budget style      thinking {"type": "enabled", "budget_tokens": N}, effort dropped
    adaptive          thinking {"type": "adaptive"}, effort passed in output_config
    always on         no thinking parameter at all, effort passed
    unknown           no thinking parameter, no effort

`temperature` is dropped whenever thinking is active, which on every family this system uses
is always. anthropic 1.5.0 removed the `temperature` argument from the SDK call anyway, so
when a caller does pin an older non thinking model the value goes through extra_body. Either
way the drop is recorded and lands in the audit event, because dropping a parameter silently
is how a provider swap turns into an afternoon of guessing.
"""
from __future__ import annotations

import json
from typing import Any

from digest.errors import DigestError
from digest.providers import Capabilities, ProviderResult, TierParams
from digest.providers._families import clamp_effort, family_for, thinking_budget_for

__all__ = ["AnthropicDirectProvider", "STREAM_ABOVE_MAX_TOKENS"]

# Above this many max_tokens a non streaming request risks a read timeout, so stream.
STREAM_ABOVE_MAX_TOKENS = 16000


class AnthropicDirectProvider:
    """One completion per call through anthropic.Anthropic.messages."""

    name = "anthropic_direct"

    def __init__(self, *, client: Any = None, api_key: str | None = None,
                 base_url: str | None = None, timeout: float = 600.0,
                 max_retries: int = 2, stream_above: int = STREAM_ABOVE_MAX_TOKENS,
                 extra_headers: dict[str, str] | None = None) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self.stream_above = stream_above
        self.extra_headers = extra_headers
        self.last_request: dict[str, Any] | None = None

    # -- interface ---------------------------------------------------------------

    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_structured=True,   # output_config.format
            strict_tools=True,        # tools with strict: true
            thinking_style="adaptive",
            effort=True,
        )

    def translate_model_id(self, canonical_model_id: str) -> str:
        """The public API takes the canonical id unchanged."""
        return canonical_model_id

    def client(self) -> Any:
        if self._client is None:
            import anthropic  # imported lazily so the seat path needs no API package

            kwargs: dict[str, Any] = {"timeout": self._timeout, "max_retries": self._max_retries}
            if self._api_key is not None:
                kwargs["api_key"] = self._api_key
            if self._base_url is not None:
                kwargs["base_url"] = self._base_url
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def build_request(self, model_id: str, system: str, user: str,
                      schema: dict, params: TierParams) -> tuple[dict[str, Any], list[str]]:
        """Build the request body for one call. Returns (kwargs, dropped_params).

        Public because the family rules are the interesting part of this adapter and a test
        that reads the body is the only honest way to prove them without a key.
        """
        family = family_for(model_id)
        dropped: list[str] = []
        max_tokens = int(params["max_tokens"])

        body: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": schema}
        }

        effort, effort_dropped = clamp_effort(params.get("effort"), family)
        dropped += effort_dropped
        if effort is not None:
            output_config["effort"] = effort
        body["output_config"] = output_config

        if family.thinking_style == "budget":
            budget = params.get("thinking_budget") or thinking_budget_for(max_tokens)
            budget = min(max(1024, int(budget)), max_tokens - 1)
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        elif family.thinking_style == "adaptive":
            # Sent explicitly for every adaptive family. Omitting it means no thinking at
            # all on the families where it must be enabled, and it is a no op on the rest,
            # so one branch is both correct and shorter than two.
            body["thinking"] = {"type": "adaptive"}
        else:
            # always_on and unknown: the parameter itself is the problem.
            if params.get("thinking_budget") is not None:
                dropped.append("thinking_budget")

        temperature = params.get("temperature")
        if temperature is not None:
            if family.thinking_active():
                dropped.append("temperature")
            else:
                body["extra_body"] = {"temperature": temperature}

        if max_tokens > self.stream_above:
            body["stream"] = True

        if self.extra_headers:
            body["extra_headers"] = dict(self.extra_headers)

        return body, dropped

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult:
        body, dropped = self.build_request(model_id, system, user, schema, params)
        self.last_request = body
        streaming = bool(body.pop("stream", False))
        client = self.client()
        try:
            if streaming:
                with client.messages.stream(**body) as stream:
                    message = stream.get_final_message()
            else:
                message = client.messages.create(**body)
        except Exception as exc:  # noqa: BLE001 - the router logs and the caller decides
            raise DigestError("anthropic_direct: request failed: %s" % exc) from exc

        stop_reason = _get(message, "stop_reason") or "end_turn"
        if stop_reason == "refusal":
            raise DigestError("anthropic_direct: the model refused the request")

        usage = _get(message, "usage")
        return ProviderResult(
            text=_first_text(message),
            tokens_in=int(_get(usage, "input_tokens") or 0),
            tokens_out=int(_get(usage, "output_tokens") or 0),
            cache_read=int(_get(usage, "cache_read_input_tokens") or 0),
            cache_write=int(_get(usage, "cache_creation_input_tokens") or 0),
            stop_reason=str(stop_reason),
            dropped_params=dropped,
            provider_reported_cost_usd=None,
            path="native_structured",
        )


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _first_text(message: Any) -> str:
    """output_config.format guarantees the first text block holds the JSON object."""
    for block in _get(message, "content") or []:
        if _get(block, "type") == "text":
            return str(_get(block, "text") or "")
        if _get(block, "type") == "tool_use":
            return json.dumps(_get(block, "input") or {}, ensure_ascii=False)
    return ""
