"""The BI theme digest agent.

Reads Gong calls and Salesforce cases, extracts client claims through bounded reader
agents, verifies every claim against its source before it is ever stored, and produces a
weekly digest whose citations resolve. See `contracts/README.md` for the schema pack that
every boundary in this package validates against, and `python -m digest --help` for the
run surface.
"""
from __future__ import annotations

__version__ = "0.1.0"
