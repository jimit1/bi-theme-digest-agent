"""An OpenAI compatible gateway: a stub with a real model id translation.

A gateway passes the model id straight through unless it has been configured with its own
names, so the translation is an explicit map and nothing else. No guessing, no prefixing:
a gateway that renamed a model and was not told about it should fail loudly at the call,
not quietly serve a different model.

This is also the one adapter that declares neither native structured output nor strict
tools, which is what exercises the router's third negotiation path: schema in the prompt,
validated in code.

`complete` raises. Nothing here pretends to work.
"""
from __future__ import annotations

from typing import Any

from digest.providers import Capabilities, ProviderResult, TierParams

__all__ = ["OpenAiCompatibleProvider"]


class OpenAiCompatibleProvider:
    """Constructor, capabilities and model id translation. Completion is not implemented."""

    name = "openai_compatible"

    def __init__(self, *, base_url: str | None = None, model_map: dict[str, str] | None = None,
                 api_key_env: str = "OPENAI_API_KEY", **options: Any) -> None:
        self.base_url = base_url
        self.model_map = dict(model_map or {})
        self.api_key_env = api_key_env
        self.options = options

    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_structured=False,
            strict_tools=False,
            thinking_style="none",
            effort=False,
        )

    def translate_model_id(self, canonical_model_id: str) -> str:
        return self.model_map.get(canonical_model_id, canonical_model_id)

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult:
        raise NotImplementedError(
            "stub: needs a chat completions client pointed at %s, a key from %s, the system "
            "prompt folded into the messages array as a system role, the contract schema "
            "embedded in the prompt because this path declares neither native structured "
            "output nor strict tools, and usage mapped from prompt_tokens and "
            "completion_tokens, which carry no cache split at all"
            % (self.base_url or "unset", self.api_key_env)
        )
