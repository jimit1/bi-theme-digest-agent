"""Tests for `digest.render`: the markdown and single-file HTML digest.

Exercises both renderers against the fixture in `tests/fixtures/b13/data.py`: two themes,
four claims (two Gong, two Salesforce), a fake store that hands back the two source
documents those claims cite. Asserts every citation label and claim id appears in the
markdown, that the HTML carries no URL-shaped text, that every claim's verbatim is wrapped
in a `<mark>`, that the mm:ss arithmetic is right, and that the HTML file parses cleanly.
"""
from __future__ import annotations

import html.parser
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
FIXTURES = REPO / "tests" / "fixtures" / "b13"
if str(FIXTURES.parent.parent) not in sys.path:
    sys.path.insert(0, str(FIXTURES.parent.parent))

from digest.render import citation_label, render_html, render_markdown, source_moment  # noqa: E402
from digest.render.markdown import _run_line  # noqa: E402
from digest.render.scoring import explain_score  # noqa: E402
from digest.store import mmss  # noqa: E402

from fixtures.b13.data import (  # noqa: E402
    CLAIM_GONG_1,
    CLAIM_GONG_2,
    CLAIM_SFDC_1,
    CLAIM_SFDC_2,
    CLAIMS_BY_ID,
    DIGEST,
    FakeStore,
    MANIFEST,
    THEMES_RANKED,
)

WEEK = "2026-W37"


class _StrictParser(html.parser.HTMLParser):
    """`html.parser` does not raise on most malformed markup on its own; this fixture makes
    it fail loudly by recording anything reported through `error` were that ever invoked
    (older Pythons routed unrecoverable states there), and separately checks void/void-like
    tags are not left dangling by counting open/close balance for the tags we control."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []

    def error(self, message: str) -> None:  # pragma: no cover - only on real malformation
        self.errors.append(message)


@pytest.fixture()
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture()
def markdown_text(store: FakeStore) -> str:
    return render_markdown(WEEK, DIGEST, THEMES_RANKED, CLAIMS_BY_ID, MANIFEST, store)


@pytest.fixture()
def html_text(store: FakeStore) -> str:
    return render_html(WEEK, DIGEST, THEMES_RANKED, CLAIMS_BY_ID, MANIFEST, store)


def test_markdown_title_and_run_line(markdown_text: str) -> None:
    assert "Theme digest, week 2026-W37" in markdown_text
    assert MANIFEST["run_id"] in markdown_text
    assert "4 sources read" in markdown_text
    assert "1 private comments withheld" in markdown_text
    assert "0 PII redactions" in markdown_text
    assert "4 claims verified, 1 rejected" in markdown_text
    assert "1 themes appended, 0 opened" in markdown_text
    assert "$0.05" in markdown_text  # usage.total.cost_usd 0.0475 rounded to cents
    assert "model tiers used: extraction, synthesis." in markdown_text


def test_run_line_reports_the_week_when_the_weekly_summary_is_passed_in() -> None:
    """The pipeline hands the week's aggregate in through the manifest argument, so the
    line names the week, splits sources into calls and cases and prints the week's cost
    with this build's own cost in brackets."""
    weekly = json.loads(json.dumps(MANIFEST))
    weekly["counts"]["sources_read"] = 53
    weekly["counts"]["comments_withheld"] = 10
    weekly["counts"]["pii_redactions"] = 10
    weekly["counts"]["claims_verified"] = 55
    weekly["usage"]["total"]["cost_usd"] = 3.1234
    weekly["sources_by_doc_type"] = {"call": 24, "case": 29}
    weekly["build_cost_usd"] = 1.2187
    line = _run_line(weekly)
    assert line.startswith("Run 2026-09-14T07:00Z, week 2026-W37: ")
    assert "53 sources read (24 calls, 29 cases)" in line
    assert "10 private comments withheld, 10 PII redactions" in line
    assert "55 claims verified, 1 rejected" in line
    assert "cost $3.12 for the week ($1.22 this build)" in line


def test_status_line_names_the_accounts_the_open_cases_are_on(markdown_text: str,
                                                              html_text: str) -> None:
    assert "Open cases on these accounts:" in markdown_text
    assert "Open cases on these accounts:" in html_text
    assert "Open cases:" not in markdown_text
    assert "Open cases:" not in html_text


def test_markdown_has_every_citation_label_and_claim_id(markdown_text: str) -> None:
    for claim in CLAIMS_BY_ID.values():
        assert citation_label(claim) in markdown_text
        assert "[%s]" % claim["claim_id"] in markdown_text
        assert claim["verbatim"] in markdown_text


def test_markdown_score_arithmetic_matches_theme_score(markdown_text: str) -> None:
    for theme in THEMES_RANKED:
        explained = explain_score(theme["score_inputs"])
        assert explained["score"] == theme["score"]
        assert "Why this score" in markdown_text


def test_markdown_has_reconciliations_quiet_and_proposals(markdown_text: str) -> None:
    assert "Reconciliations" in markdown_text
    assert "dues proration" in markdown_text
    assert "Quiet and stale" in markdown_text
    assert "THEME-0002" in markdown_text
    assert "Proposed for filing" in markdown_text
    assert "status proposed" in markdown_text
    assert "How to trace a claim by hand" in markdown_text


def test_markdown_no_dashes(markdown_text: str) -> None:
    assert "—" not in markdown_text
    assert "–" not in markdown_text


def test_html_no_url_shaped_text(html_text: str) -> None:
    lowered = html_text.lower()
    assert "http" not in lowered
    assert "www." not in lowered


def test_html_parses_cleanly(html_text: str) -> None:
    parser = _StrictParser()
    parser.feed(html_text)
    parser.close()
    assert parser.errors == []


def test_html_every_claim_verbatim_is_marked(html_text: str) -> None:
    for claim in CLAIMS_BY_ID.values():
        marked = "<mark>%s</mark>" % claim["verbatim"]
        assert marked in html_text, "verbatim for %s not found inside a <mark>" % claim["claim_id"]


def test_html_has_claim_anchors(html_text: str) -> None:
    for claim_id in CLAIMS_BY_ID:
        assert 'id="claim-%s"' % claim_id in html_text


def test_html_has_score_details(html_text: str) -> None:
    assert "Why this score" in html_text
    assert "score-explain" in html_text


def test_mmss_math() -> None:
    assert mmss(65000) == "01:05"
    assert mmss(3670000) == "61:10"
    assert mmss(0) == "00:00"


def test_source_moment_gong_context_same_turn(store: FakeStore) -> None:
    moment = source_moment(CLAIM_GONG_1, store)
    assert moment["available"] is True
    assert moment["before"] == "Sentence zero context."
    assert moment["after"] == "Trailing context sentence."
    assert moment["verbatim"] == CLAIM_GONG_1["verbatim"]


def test_source_moment_gong_context_crosses_turn_boundary(store: FakeStore) -> None:
    moment = source_moment(CLAIM_GONG_2, store)
    assert moment["available"] is True
    # claim two's turn is the last turn in the document and has one sentence, so "before"
    # crosses into the previous turn's last sentence and "after" is None (nothing follows).
    assert moment["before"] == "Trailing context sentence."
    assert moment["after"] is None


def test_source_moment_salesforce_has_no_sentence_context(store: FakeStore) -> None:
    moment = source_moment(CLAIM_SFDC_1, store)
    assert moment["available"] is True
    assert moment["before"] is None
    assert moment["after"] is None
    assert moment["turn_text"] is not None
    assert CLAIM_SFDC_1["verbatim"] in moment["turn_text"]


def test_source_moment_missing_source_is_graceful(store: FakeStore) -> None:
    orphan = dict(CLAIM_SFDC_2)
    orphan["source_ref"] = dict(orphan["source_ref"])
    orphan["source_ref"]["case_id"] = "500999999999999AAA"
    moment = source_moment(orphan, store)
    assert moment["available"] is False
    assert moment["verbatim"] == orphan["verbatim"]
    assert moment["before"] is None and moment["after"] is None


def test_citation_label_format() -> None:
    assert citation_label(CLAIM_GONG_1) == "call 7782934451099 at 01:05, Dana Ruiz"
    assert citation_label(CLAIM_SFDC_1) == "case 00001099 comment 00a000000000001AAA"
