"""Microsoft Foundry: a stub with a real model id translation.

Foundry addresses a deployment, not a model. The deployment name is chosen by whoever
created it, so the translation is a lookup with the canonical id as the fallback: a
per model map first, then a single default deployment, then the canonical id unchanged.

`complete` raises. Nothing here pretends to work.
"""
from __future__ import annotations

from typing import Any

from digest.providers import Capabilities, ProviderResult, TierParams

__all__ = ["FoundryProvider"]


class FoundryProvider:
    """Constructor, capabilities and model id translation. Completion is not implemented."""

    name = "foundry"

    def __init__(self, *, endpoint: str | None = None, deployment: str | None = None,
                 deployments: dict[str, str] | None = None,
                 api_version: str | None = None, **options: Any) -> None:
        self.endpoint = endpoint
        self.deployment = deployment
        self.deployments = dict(deployments or {})
        self.api_version = api_version
        self.options = options

    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_structured=False,
            strict_tools=True,
            thinking_style="budget",
            effort=False,
        )

    def translate_model_id(self, canonical_model_id: str) -> str:
        if canonical_model_id in self.deployments:
            return self.deployments[canonical_model_id]
        if self.deployment:
            return self.deployment
        return canonical_model_id

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult:
        raise NotImplementedError(
            "stub: needs a Foundry endpoint (%s), an Entra token or key credential, an "
            "api-version query parameter, a deployment that exists in the resource, the "
            "contract schema wrapped as a strict tool, and usage mapped from the Foundry "
            "response envelope" % (self.endpoint or "unset")
        )
