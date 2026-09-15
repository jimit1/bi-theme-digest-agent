"""Model family rules, the one place per model API differences live.

A family is detected from a substring of the model id, never from an exact id, so a
platform prefixed id (Bedrock puts a vendor prefix in front, Vertex swaps the version
separator) still lands on the right rules. No full model id appears here; config/models.yaml
is the only runtime file that names one.

Why this file exists at all: thinking and effort handling is a property of the model
family, and getting it wrong returns a 400 that configuration cannot explain. Putting the
rules in one table means a provider swap reads them once instead of rediscovering them.

The four styles, matching Capabilities.thinking_style:

    adaptive    thinking is adaptive; send {"type": "adaptive"} or omit it
    budget      older interface; send {"type": "enabled", "budget_tokens": N}
    always_on   thinking cannot be turned off; send no thinking parameter at all
    none        unknown family; send no thinking parameter and no effort
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Family",
    "family_for",
    "thinking_budget_for",
    "clamp_effort",
    "EFFORT_LEVELS",
]

EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class Family:
    """What one model family accepts. Everything an adapter needs to avoid a 400."""

    key: str
    thinking_style: str          # adaptive | budget | always_on | none
    explicit_adaptive: bool      # true when omitting thinking means no thinking at all
    effort: bool                 # false when the family rejects an effort parameter
    max_effort: str | None       # highest effort level the family accepts
    forced_tool_choice: bool     # false when tool_choice any/tool returns 400
    prefill: bool                # false when an assistant prefill is rejected

    def accepts_thinking_param(self) -> bool:
        return self.thinking_style in ("adaptive", "budget")

    def thinking_active(self) -> bool:
        """Thinking is on for everything except an unknown family."""
        return self.thinking_style != "none"


# Ordered longest and most specific first. The matcher walks this list in order and takes
# the first substring hit, so opus 4.6 is tested before the generic opus entries.
_ADAPTIVE = dict(thinking_style="adaptive", explicit_adaptive=False, effort=True,
                 max_effort="max", forced_tool_choice=True, prefill=False)

_RULES: list[tuple[str, Family]] = [
    ("fable", Family(key="fable", thinking_style="always_on", explicit_adaptive=False,
                     effort=True, max_effort="max", forced_tool_choice=False, prefill=False)),
    ("mythos", Family(key="mythos", thinking_style="always_on", explicit_adaptive=False,
                      effort=True, max_effort="max", forced_tool_choice=False, prefill=False)),
    ("haiku-4-5", Family(key="haiku-4-5", thinking_style="budget", explicit_adaptive=False,
                         effort=False, max_effort=None, forced_tool_choice=True, prefill=True)),
    ("opus-4-6", Family(key="opus-4-6", thinking_style="adaptive", explicit_adaptive=True,
                        effort=True, max_effort="high", forced_tool_choice=True, prefill=True)),
    ("sonnet-4-6", Family(key="sonnet-4-6", thinking_style="adaptive", explicit_adaptive=True,
                          effort=True, max_effort="high", forced_tool_choice=True, prefill=True)),
    ("opus-4-7", Family(key="opus-4-7", **_ADAPTIVE)),
    ("opus-4-8", Family(key="opus-4-8", **_ADAPTIVE)),
    ("opus-5", Family(key="opus-5", **_ADAPTIVE)),
    ("sonnet-5", Family(key="sonnet-5", **_ADAPTIVE)),
    ("haiku", Family(key="haiku", thinking_style="budget", explicit_adaptive=False,
                     effort=False, max_effort=None, forced_tool_choice=True, prefill=True)),
]

_UNKNOWN = Family(key="unknown", thinking_style="none", explicit_adaptive=False,
                  effort=False, max_effort=None, forced_tool_choice=True, prefill=True)


def family_for(model_id: str) -> Family:
    """Detect the family of a model id, platform prefixes and version separators included.

    An id the table does not recognise returns the `unknown` family, which sends no
    thinking parameter and no effort. A wrong guess on an unknown model is a silent
    behaviour change; refusing to guess is a missing feature, and the second is cheaper.
    """
    probe = (model_id or "").lower().replace("@", "-")
    for needle, family in _RULES:
        if needle in probe:
            return family
    return _UNKNOWN


def thinking_budget_for(max_tokens: int) -> int:
    """The pinned budget for budget style families, so two adapters compute one number.

    The API wants 1024 <= budget < max_tokens. Half of max_tokens is the starting point,
    floored at the minimum and capped one token below the ceiling.
    """
    return min(max(1024, max_tokens // 2), max_tokens - 1)


def clamp_effort(effort: str | None, family: Family) -> tuple[str | None, list[str]]:
    """Return the effort the family will accept, plus the names of anything dropped."""
    dropped: list[str] = []
    if effort is None:
        return None, dropped
    if not family.effort:
        return None, ["effort"]
    ceiling = family.max_effort
    if ceiling is not None and EFFORT_LEVELS.index(effort) > EFFORT_LEVELS.index(ceiling):
        dropped.append("effort:%s->%s" % (effort, ceiling))
        return ceiling, dropped
    return effort, dropped
