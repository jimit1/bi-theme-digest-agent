"""The digest renderer: markdown and single-file HTML from the same inputs.

Created by task B13 per the orchestrator's note (the package did not exist yet and no other
task owns this file). Re-exports the public surface so callers write
`from digest.render import render_markdown, render_html` rather than reaching into the
submodules directly.
"""
from __future__ import annotations

from digest.render.citations import citation_label, source_moment
from digest.render.html import render_html
from digest.render.markdown import render_markdown
from digest.render.scoring import explain_score

__all__ = [
    "render_markdown",
    "render_html",
    "source_moment",
    "citation_label",
    "explain_score",
]
