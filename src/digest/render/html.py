"""The single-file HTML digest: `render_html`.

Same signature note as `digest.render.markdown`: this follows `build/briefs/B13.md`'s
`render_html(week, digest, themes_ranked, claims_by_id, manifest, store)`, not the flatter
signature in `contracts/INTERFACES.md`, because the editor's headline, summary,
reconciliations, quiet/stale notes and filing proposals have no home in that signature's
`themes`/`claims`/`manifest` objects (all `additionalProperties: false` against schemas that
do not carry them). See `digest/render/markdown.py` for the full note.

One file. Inline CSS, one small inline script, no network requests, no external font or
CDN. Every evidence item is a `<details>` that expands to the source moment; every claim
gets an `id="claim-<id>"` anchor so other documents can link `#claim-<id>`.
"""
from __future__ import annotations

import html as html_lib
from typing import Any

from digest.render.citations import citation_label, source_moment
from digest.render.markdown import _proposed_for_filing, _quiet_and_stale, _run_line
from digest.render.scoring import explain_score
from digest.store import Store, mmss

__all__ = ["render_html"]


def _esc(text: Any) -> str:
    """Escape for a text node. `quote=False`: this never lands inside an attribute value,
    and leaving straight quotes alone keeps a quoted verbatim an exact substring match
    inside its <mark>, which is what the citation-trace test asserts on."""
    return html_lib.escape(str(text), quote=False)


_STYLE = """
:root { color-scheme: light dark; --fg: #1a1a1a; --bg: #ffffff; --muted: #555555;
  --border: #cccccc; --mark-bg: #fff2a8; --mark-fg: #1a1a1a; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6e6e6; --bg: #121212; --muted: #a0a0a0; --border: #3a3a3a;
    --mark-bg: #7a6a00; --mark-fg: #ffffff; }
}
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color: var(--fg);
  background: var(--bg); max-width: 860px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
h1, h2, h3 { line-height: 1.25; }
.run-line, .status { color: var(--muted); font-size: 0.92em; }
mark { background: var(--mark-bg); color: var(--mark-fg); padding: 0 0.1em; }
details { border: 1px solid var(--border); border-radius: 6px; padding: 0.4em 0.7em; margin: 0.4em 0; }
summary { cursor: pointer; }
.evidence { list-style: none; padding-left: 0; }
.moment p { margin: 0.4em 0; }
.meta { color: var(--muted); font-size: 0.9em; }
@media print { body { max-width: none; } details { border: none; padding: 0; } }
"""

_SCRIPT = """
(function () {
  function openTarget() {
    var id = window.location.hash.slice(1);
    if (!id) { return; }
    var el = document.getElementById(id);
    if (el && el.tagName === 'LI') {
      var d = el.querySelector('details');
      if (d) { d.open = true; }
      el.scrollIntoView();
    }
  }
  window.addEventListener('hashchange', openTarget);
  openTarget();
})();
"""


def render_html(
    week: str,
    digest: dict[str, Any],
    themes_ranked: list[dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    store: Store,
) -> str:
    ordered = sorted(themes_ranked, key=lambda t: (-int(t["score"]), t["theme_id"]))
    sections_by_theme = {s["theme_id_or_placeholder"]: s for s in digest.get("sections", [])}

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append("<title>%s</title>" % _esc("Theme digest, week %s" % week))
    parts.append("<style>%s</style>" % _STYLE)
    parts.append("</head><body>")
    parts.append("<h1>%s</h1>" % _esc("Theme digest, week %s" % week))
    parts.append('<p class="run-line">%s</p>' % _esc(_run_line(manifest)))
    parts.append("<h2>%s</h2>" % _esc(digest["headline"]))
    parts.append("<p>%s</p>" % _esc(digest["summary"]))

    for position, theme in enumerate(ordered, start=1):
        parts.append(_theme_html(position, theme, sections_by_theme, claims_by_id, store))

    parts.append("<h2>Reconciliations</h2>")
    reconciliations = digest.get("reconciliations", [])
    if not reconciliations:
        parts.append("<p>None this run.</p>")
    else:
        parts.append("<ul>")
        for item in reconciliations:
            names = ", ".join('"%s"' % _esc(n) for n in item["names"])
            parts.append(
                "<li>%s: %s are the same thing. %s</li>"
                % (_esc(item["theme_id_or_placeholder"]), names, _esc(item["note"]))
            )
        parts.append("</ul>")

    parts.append("<h2>Quiet and stale</h2><ul>")
    for line in _quiet_and_stale(ordered, digest.get("quiet_or_stale_notes", [])):
        parts.append("<li>%s</li>" % _esc(line.lstrip("- ")))
    parts.append("</ul>")

    parts.append("<h2>Proposed for filing</h2><ul>")
    for line in _proposed_for_filing(week, store):
        parts.append("<li>%s</li>" % _esc(line.lstrip("- ")))
    parts.append("</ul>")

    parts.append("<h2>How to trace a claim by hand</h2>")
    parts.append(
        "<p>Open the source file for the id in the citation label in square brackets "
        "in the store, using the call id for a Gong moment or the case id for a "
        "Salesforce one. Find the turn whose reference matches the claim, then find the "
        "quoted text as an exact match inside that turn.</p>"
    )

    parts.append("<script>%s</script>" % _SCRIPT)
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def _theme_html(
    position: int,
    theme: dict[str, Any],
    sections_by_theme: dict[str, dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
    store: Store,
) -> str:
    parts: list[str] = []
    parts.append('<section id="theme-%s">' % _esc(theme["theme_id"]))
    parts.append(
        "<h3>%d. %s (score %d)</h3>"
        % (position, _esc(theme["title"]), theme["score"])
    )
    parts.append('<p class="status">%s</p>' % _esc(_status_line_plain(theme)))

    section = sections_by_theme.get(theme["theme_id"])
    body = section["body"] if section is not None else theme["rationale"]
    parts.append("<p>%s</p>" % _esc(body))

    parts.append('<ul class="evidence">')
    for claim_id in theme["evidence"]:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            parts.append(
                '<li id="claim-%s">claim %s is not in this run\'s claim map</li>'
                % (_esc(claim_id), _esc(claim_id))
            )
            continue
        parts.append(_evidence_item(claim, store))
    parts.append("</ul>")

    parts.append(_score_details(theme))
    parts.append("</section>")
    return "\n".join(parts)


def _status_line_plain(theme: dict[str, Any]) -> str:
    inputs = theme["score_inputs"]
    text = (
        "Accounts: %d customer, %d prospect. Open cases on these accounts: %d. "
        "Last evidence: %s. Status: %s."
        % (
            inputs["distinct_customers"],
            inputs["distinct_prospects"],
            inputs["open_cases"],
            theme["last_evidence_at"][:10],
            theme["status"],
        )
    )
    if theme["status"] == "quiet":
        text += " QUIET: no new evidence and the newest is %d days old." % inputs["recency_days"]
    if theme["stale"]:
        text += " STALE: %s" % theme["stale_reason"]
    return text


def _evidence_item(claim: dict[str, Any], store: Store) -> str:
    claim_id = claim["claim_id"]
    label = citation_label(claim)
    summary = '"%s" : %s (%s), %s [%s]' % (
        claim["verbatim"],
        claim["account_name"],
        claim["account_type"],
        label,
        claim_id,
    )
    moment = source_moment(claim, store)
    body = _moment_html(claim, moment)
    return (
        '<li id="claim-%s"><details><summary>%s</summary>%s</details></li>'
        % (_esc(claim_id), _esc(summary), body)
    )


def _moment_html(claim: dict[str, Any], moment: dict[str, Any]) -> str:
    verbatim = moment["verbatim"]
    meta_lines: list[str] = []
    if moment["source"] == "gong":
        ref = claim["source_ref"]
        meta_lines.append(
            "Call %s, %s, %s (%s), offset %s"
            % (
                _esc(ref["call_id"]),
                _esc((moment.get("occurred_at") or "")[:10] or "date unknown"),
                _esc(moment.get("speaker") or "unknown speaker"),
                _esc(claim["speaker_side"]),
                _esc(mmss(int(ref["start_ms"]))),
            )
        )
    else:
        ref = claim["source_ref"]
        meta_lines.append(
            "Case %s, comment %s, %s (%s), %s"
            % (
                _esc(ref["case_number"]),
                _esc(ref["comment_id"]),
                _esc(moment.get("speaker") or "unknown author"),
                _esc(claim["speaker_side"]),
                _esc(ref["created_at"]),
            )
        )

    if not moment["available"]:
        content = "<p>Context unavailable: <mark>%s</mark></p>" % _esc(verbatim)
    elif moment["source"] == "gong":
        segments: list[str] = []
        if moment.get("before"):
            segments.append(_esc(moment["before"]))
        segments.append("<mark>%s</mark>" % _esc(verbatim))
        if moment.get("after"):
            segments.append(_esc(moment["after"]))
        content = "<p>%s</p>" % " ".join(segments)
    else:
        turn_text = moment.get("turn_text")
        if turn_text and verbatim in turn_text:
            idx = turn_text.find(verbatim)
            before_text = turn_text[:idx]
            after_text = turn_text[idx + len(verbatim):]
            content = "<p>%s<mark>%s</mark>%s</p>" % (
                _esc(before_text),
                _esc(verbatim),
                _esc(after_text),
            )
        else:
            content = "<p><mark>%s</mark></p>" % _esc(verbatim)

    return '<div class="moment"><p class="meta">%s</p>%s</div>' % (
        "".join(meta_lines),
        content,
    )


def _score_details(theme: dict[str, Any]) -> str:
    explained = explain_score(theme["score_inputs"])
    rows = "".join(
        "<li>%s: %s = %.2f</li>" % (_esc(name), _esc(formula), value)
        for name, formula, value in explained["terms"]
    )
    penalty_note = " (prospect-only theme, halved)" if explained["penalty"] else ""
    return (
        '<details class="score-explain"><summary>Why this score: %d</summary>'
        "<ul>%s</ul><p>Subtotal %.2f%s, floor(+0.5), clamped: %d.</p></details>"
        % (theme["score"], rows, explained["total"], _esc(penalty_note), explained["score"])
    )
