"""Google Vertex AI: a stub with a real model id translation.

Vertex separates the version from the model name with `@` where the canonical id uses a
hyphen. Only a dated id has a version to separate, so an undated id passes through
unchanged rather than growing an `@` that Vertex would reject.

    <name>-<8 digit date>  -> <name>@<8 digit date>
    <name>                 -> <name>

`complete` raises. Nothing here pretends to work.
"""
from __future__ import annotations

import re
from typing import Any

from digest.providers import Capabilities, ProviderResult, TierParams

__all__ = ["VertexProvider", "VERSION_SUFFIX"]

# A trailing date is the only version suffix Vertex separates with @.
VERSION_SUFFIX = re.compile(r"^(?P<name>.+)-(?P<version>\d{8})$")


class VertexProvider:
    """Constructor, capabilities and model id translation. Completion is not implemented."""

    name = "vertex"

    def __init__(self, *, project: str | None = None, region: str = "us-east5",
                 model_map: dict[str, str] | None = None, **options: Any) -> None:
        self.project = project
        self.region = region
        self.model_map = dict(model_map or {})
        self.options = options

    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_structured=False,
            strict_tools=True,
            thinking_style="budget",
            effort=False,
        )

    def translate_model_id(self, canonical_model_id: str) -> str:
        if canonical_model_id in self.model_map:
            return self.model_map[canonical_model_id]
        if "@" in canonical_model_id:
            return canonical_model_id
        match = VERSION_SUFFIX.match(canonical_model_id)
        if not match:
            return canonical_model_id
        return "%s@%s" % (match.group("name"), match.group("version"))

    def complete(self, model_id: str, system: str, user: str,
                 schema: dict, params: TierParams) -> ProviderResult:
        raise NotImplementedError(
            "stub: needs the anthropic AnthropicVertex client, a Google application default "
            "credential with aiplatform scope, a project id (%s) and a region (%s) that "
            "actually carries the model, the contract schema wrapped as a strict tool, and "
            "a dated model id because Vertex does not serve the undated alias"
            % (self.project or "unset", self.region)
        )
