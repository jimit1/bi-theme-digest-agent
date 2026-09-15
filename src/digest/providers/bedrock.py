"""Amazon Bedrock: a stub with a real model id translation.

The translation is the part that actually differs and the part that eats an afternoon when
it is discovered late, so it is implemented for real and tested. Bedrock ids carry a vendor
prefix in front of the canonical id, and a cross region inference profile puts a region
group in front of that again.

    canonical                 -> anthropic.<canonical>
    canonical, cross region   -> us.anthropic.<canonical>

`complete` raises. Nothing here pretends to work.
"""
from __future__ import annotations

from typing import Any

from digest.providers import Capabilities, ProviderResult, TierParams

__all__ = ["BedrockProvider", "VENDOR_PREFIX"]

VENDOR_PREFIX = "anthropic."


class BedrockProvider:
    """Constructor, capabilities and model id translation. Completion is not implemented."""

    name = "bedrock"

    def __init__(self, *, region: str = "us-east-1", cross_region: bool = False,
                 region_group: str = "us", profile: str | None = None,
                 model_map: dict[str, str] | None = None, **options: Any) -> None:
        self.region = region
        self.cross_region = cross_region
        self.region_group = region_group
        self.profile = profile
        self.model_map = dict(model_map or {})
        self.options = options

    def capabilities(self) -> Capabilities:
        # Bedrock exposes the Anthropic message API without the native structured output
        # format, so a strict tool is the strongest path a real implementation would get.
        return Capabilities(
            native_structured=False,
            strict_tools=True,
            thinking_style="budget",
            effort=False,
        )

    def translate_model_id(self, canonical_model_id: str) -> str:
        if canonical_model_id in self.model_map:
            return self.model_map[canonical_model_id]
        base = canonical_model_id
        if not base.startswith(VENDOR_PREFIX):
            base = VENDOR_PREFIX + base
        if self.cross_region and not base.startswith(self.region_group + "."):
            base = "%s.%s" % (self.region_group, base)
        return base

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult:
        raise NotImplementedError(
            "stub: needs a boto3 bedrock-runtime client, SigV4 credentials for region %s, "
            "an InvokeModel or Converse call carrying anthropic_version in the body, the "
            "contract schema wrapped as a strict tool because Bedrock has no native "
            "structured output format, and usage read from the Bedrock response rather "
            "than from the Anthropic usage block" % self.region
        )
