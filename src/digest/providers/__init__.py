"""The provider seam: one interface, six adapters, two of them real.

Every adapter answers the same three questions. What can you do (`capabilities`), what do
you call this model (`translate_model_id`), and give me one completion (`complete`). The
router talks to nothing else, which is what makes swapping a platform a config edit rather
than a refactor.

Two adapters work: `agent_sdk_seat` (the `claude` CLI on a Claude seat, no API key) and
`anthropic_direct` (the `anthropic` package). Four are honest stubs: `bedrock`, `vertex`,
`foundry` and `openai_compatible`. Each stub implements its constructor, its capability
declaration and its model id translation for real, and raises NotImplementedError from
`complete` with a sentence naming what a real implementation still needs. Translation is
the part that actually differs between platforms, so it is the part the stubs do not fake.

Imports are lazy on purpose: `import digest.providers` must not require the `anthropic`
package to be installed for the seat path to work, and must not shell out to anything.
"""
from __future__ import annotations

import importlib
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

__all__ = [
    "Capabilities",
    "TierParams",
    "ProviderResult",
    "Provider",
    "get_provider",
    "PROVIDER_NAMES",
]


class Capabilities(TypedDict):
    """What an adapter can do. The router negotiates the structured output path from this."""

    native_structured: bool
    strict_tools: bool
    thinking_style: Literal["adaptive", "budget", "always_on", "none"]
    effort: bool


class TierParams(TypedDict):
    """One tier's sampling settings, read from config/models.yaml by the router."""

    max_tokens: int
    effort: str | None
    thinking_budget: int | None
    temperature: float | None


class ProviderResult(TypedDict, total=False):
    """One completion. `text` is the JSON the router parses and validates.

    The first six keys are always present. `dropped_params` and
    `provider_reported_cost_usd` are extras an adapter fills when it has them; the router
    puts them in the audit event and keeps them out of the recorded response, whose schema
    is closed.
    """

    text: str
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_write: int
    stop_reason: str
    dropped_params: list[str]
    provider_reported_cost_usd: float | None
    path: str


@runtime_checkable
class Provider(Protocol):
    """The only thing the router knows about a platform."""

    name: str

    def capabilities(self) -> Capabilities: ...

    def translate_model_id(self, canonical_model_id: str) -> str: ...

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult: ...


PROVIDER_NAMES = (
    "agent_sdk_seat",
    "anthropic_direct",
    "bedrock",
    "vertex",
    "foundry",
    "openai_compatible",
)

_CLASSES = {
    "agent_sdk_seat": ("digest.providers.agent_sdk_seat", "AgentSdkSeatProvider"),
    "anthropic_direct": ("digest.providers.anthropic_direct", "AnthropicDirectProvider"),
    "bedrock": ("digest.providers.bedrock", "BedrockProvider"),
    "vertex": ("digest.providers.vertex", "VertexProvider"),
    "foundry": ("digest.providers.foundry", "FoundryProvider"),
    "openai_compatible": ("digest.providers.openai_compatible", "OpenAiCompatibleProvider"),
}


def get_provider(name: str, **options: Any) -> Provider:
    """Build an adapter by name. Unknown names raise ValueError, never a default.

    A typo in config/models.yaml that quietly fell back to a working provider would make
    the whole agnosticism claim unverifiable, so there is no fallback.
    """
    try:
        module_name, class_name = _CLASSES[name]
    except KeyError:
        raise ValueError(
            "unknown provider %r, expected one of: %s" % (name, ", ".join(PROVIDER_NAMES))
        ) from None
    module = importlib.import_module(module_name)
    return getattr(module, class_name)(**options)
