"""The store and the run log, exercised against a real git repository in a temp directory.

What is asserted here is what the store promises to everyone else: a theme round trips
through frontmatter that still validates, layer 1 is regenerated from layer 2 rather than
edited, evidence is append only, the watermark survives a round trip, a commit carries the
contract's author and message format, a read only store skips instead of failing, every
audit line validates, and the summary arithmetic matches the events it was derived from.

Two of these are governance controls rather than convenience: the store has no API that can
write unscrubbed source text, and a scrub event cannot carry anything but counts.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from digest.audit import Audit, COUNT_FIELDS, PII_KINDS, REJECT_REASONS  # noqa: E402
from digest.contracts import validate  # noqa: E402
from digest.errors import ContractViolation  # noqa: E402
from digest.store import (  # noqa: E402
    COMMIT_AUTHOR,
    SOURCE_ROW_RE,
    THEME_INDEX_LINE_RE,
    Store,
    mmss,
    render_theme_body,
    source_ref_label,
)

EXAMPLES = REPO / "contracts" / "examples"
RUN_ID = "2026-09-14T07:00Z"
INGEST_RUN = "2026-09-08T06:00Z"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / ("%s.example.json" % name)).read_text(encoding="utf-8"))


def _theme() -> dict:
    return {
        "schema_version": "1.0.0",
        "theme_id": "THEME-0001",
        "title": "Renewal invoices do not show prior dues credit",
        "aliases": ["dues proration", "credit on renewal"],
        "product_area": "membership",
        "status": "open",
        "owner": "ai-operations",
        "source": "synthesized",
        "last_verified": "2026-09-14",
        "run_id": RUN_ID,
        "created_run": RUN_ID,
        "last_updated_run": RUN_ID,
        "accounts": ["ACC-0001", "ACC-0003"],
        "evidence": ["e7e3c117f5c5", "df11dfd159ae"],
        "score": 74,
        "score_inputs": {
            "distinct_customers": 2, "distinct_prospects": 0, "arr_sum": 494000,
            "open_cases": 3, "recency_days": 1, "claim_count": 2, "high_importance_count": 2,
        },
        "rationale": "Two customers raised the same renewal credit gap in the same week, "
                     "and finance corrects every affected invoice by hand.",
        "stale": False,
        "stale_reason": None,
        "last_evidence_at": "2026-09-10T14:22:05.000Z",
        "proposal_id": "2026-W37/THEME-0001",
        "filed_issue_url": None,
    }


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """A scaffolded store in a temp directory, with git initialised in that directory only."""
    monkeypatch.delenv("DIGEST_STORE_READONLY", raising=False)
    monkeypatch.delenv("DIGEST_STORE_PUSH", raising=False)
    root = tmp_path / "bi-theme-digest-store"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   capture_output=True, text=True)
    s = Store(root)
    (root / "ROUTER.md").write_text("---\nschema_version: \"1.0.0\"\n---\n\n# ROUTER\n",
                                    encoding="utf-8")
    s.write_theme_index([], RUN_ID)
    s._write_sources_index(None, None, [], run_id=RUN_ID, last_verified="2026-09-14")
    s.attach_audit(Audit(RUN_ID, root))
    return s


# ----------------------------------------------------------------- themes and the index


def test_theme_round_trip_and_index_is_regenerated(store: Store) -> None:
    theme = _theme()
    claim = _example("Claim")
    path = store.write_theme(theme, render_theme_body(theme, [claim]))
    assert path.name == "THEME-0001.md"

    read_back, body = store.read_theme("THEME-0001")
    assert read_back == theme
    validate(read_back, "Theme")
    assert "## Why this matters" in body
    assert "| claim_id | account | source | moment | verbatim |" in body
    assert "call 7782934451002 at 06:58" in body
    assert claim["verbatim"] in body

    index_text = store.theme_index_path.read_text(encoding="utf-8")
    line = [l for l in index_text.split("\n") if l.startswith("| THEME-")][0]
    assert THEME_INDEX_LINE_RE.match(line), line

    lines = store.read_theme_index()
    assert len(lines) == 1
    assert lines[0]["theme_id"] == "THEME-0001"
    assert lines[0]["accounts_count"] == 2
    assert lines[0]["evidence_count"] == 2
    assert lines[0]["aliases"] == ["dues proration", "credit on renewal"]

    # Layer 1 is derived. Rebuilding from layer 2 reproduces the same bytes.
    store.rebuild_index()
    assert store.theme_index_path.read_text(encoding="utf-8") == index_text


def test_index_sort_is_score_then_id_and_empty_aliases_render_as_dash(store: Store) -> None:
    for theme_id, score, aliases in [("THEME-0001", 61, []), ("THEME-0002", 74, ["x"]),
                                     ("THEME-0003", 74, [])]:
        theme = _theme()
        theme.update(theme_id=theme_id, score=score, aliases=aliases,
                     proposal_id="2026-W37/%s" % theme_id)
        store.write_theme(theme, render_theme_body(theme, []))
    lines = store.read_theme_index()
    assert [l["theme_id"] for l in lines] == ["THEME-0002", "THEME-0003", "THEME-0001"]
    assert lines[1]["aliases"] == []
    assert "| - |" in store.theme_index_path.read_text(encoding="utf-8")


def test_bad_index_line_is_a_contract_violation_naming_the_line(store: Store) -> None:
    text = store.theme_index_path.read_text(encoding="utf-8")
    store.theme_index_path.write_text(text + "| THEME-1 | broken |\n", encoding="utf-8")
    with pytest.raises(ContractViolation) as caught:
        store.read_theme_index()
    assert caught.value.schema_name == "ThemeIndexLine"
    assert "line 13" in caught.value.errors[0]


def test_write_theme_rejects_a_document_that_fails_the_schema(store: Store) -> None:
    theme = _theme()
    theme["score"] = 400
    with pytest.raises(ContractViolation):
        store.write_theme(theme, "body")


def test_allocate_theme_ids_continues_from_the_index_and_is_stable(store: Store) -> None:
    theme = _theme()
    theme["theme_id"] = "THEME-0007"
    store.write_theme(theme, render_theme_body(theme, []))
    assert store.allocate_theme_ids(["NEW-2", "NEW-1"]) == {
        "NEW-1": "THEME-0008", "NEW-2": "THEME-0009",
    }
    assert store.allocate_theme_ids(["NEW-1", "NEW-2"]) == {
        "NEW-1": "THEME-0008", "NEW-2": "THEME-0009",
    }


def test_pipe_in_a_title_becomes_a_slash_so_the_row_still_parses(store: Store) -> None:
    theme = _theme()
    theme["title"] = "Exports | truncate"
    store.write_theme(theme, render_theme_body(theme, []))
    line = [l for l in store.theme_index_path.read_text(encoding="utf-8").split("\n")
            if l.startswith("| THEME-")][0]
    assert THEME_INDEX_LINE_RE.match(line)
    assert "Exports / truncate" in line


# ----------------------------------------------------------------- evidence


def test_append_claims_and_rejected_are_append_only(store: Store) -> None:
    claim = _example("Claim")
    rejected = _example("RejectedClaim")
    assert store.append_claims(INGEST_RUN, [claim]) == 1
    assert store.append_claims(INGEST_RUN, [claim]) == 1
    assert store.append_rejected(INGEST_RUN, [rejected]) == 1

    path = store.claims_path(INGEST_RUN)
    assert path.name == "2026-09-08T06:00Z.jsonl"
    assert len(path.read_text(encoding="utf-8").strip().split("\n")) == 2
    assert len(store.read_claims([INGEST_RUN])) == 2
    assert len(store.read_claims()) == 2


def test_append_claims_rejects_an_invalid_claim_before_writing(store: Store) -> None:
    bad = _example("Claim")
    bad["claim_id"] = "nope"
    with pytest.raises(ContractViolation) as caught:
        store.append_claims(INGEST_RUN, [bad])
    assert "item 0" in caught.value.errors[0]
    assert not store.claims_path(INGEST_RUN).exists()


def test_read_claims_by_week_resolves_through_the_sources_index(store: Store) -> None:
    doc = _example("SourceDocument")
    store.record_sources(INGEST_RUN, [doc])
    store.append_claims(INGEST_RUN, [_example("Claim")])
    assert store.ingest_runs_for_week("2026-W37") == [INGEST_RUN]
    assert len(store.read_claims(week="2026-W37")) == 1
    # An empty index still answers, from the pinned calendar.
    assert Store(store.path / "nope").ingest_runs_for_week("2026-W37") == [
        "2026-09-07T06:00Z", "2026-09-08T06:00Z", "2026-09-09T06:00Z",
        "2026-09-10T06:00Z", "2026-09-11T06:00Z",
    ]


# ----------------------------------------------------------------- sources and watermark


def test_watermark_round_trip(store: Store) -> None:
    assert store.read_watermark() == (None, None)
    store.write_watermark(INGEST_RUN, datetime.date(2026, 9, 8))
    assert store.read_watermark() == (INGEST_RUN, datetime.date(2026, 9, 8))
    text = store.sources_index_path.read_text(encoding="utf-8")
    assert "last_ingest_run: 2026-09-08T06:00Z" in text
    assert "last_ingest_day: 2026-09-08" in text


def test_record_sources_appends_rows_the_contract_regex_accepts(store: Store) -> None:
    doc = _example("SourceDocument")
    store.write_watermark(INGEST_RUN, "2026-09-08")
    store.record_sources(INGEST_RUN, [doc])
    store.record_sources(INGEST_RUN, [doc])  # same source twice is still one row
    rows = store.read_source_rows()
    assert len(rows) == 1
    assert rows[0]["turn_count"] == 1
    assert rows[0]["withheld_comment_count"] == 0
    row_line = [l for l in store.sources_index_path.read_text(encoding="utf-8").split("\n")
                if l.startswith("| gong ")][0]
    assert SOURCE_ROW_RE.match(row_line), row_line
    # Recording sources does not move the watermark; that is a separate, deliberate write.
    assert store.read_watermark() == (INGEST_RUN, datetime.date(2026, 9, 8))


def test_the_store_has_no_unscrubbed_path(store: Store) -> None:
    """The control, asserted rather than promised: nothing here writes raw source text."""
    doc = _example("SourceDocument")
    path = store.write_source_document(doc)
    assert path.name == "7782934451002.json"
    assert store.read_source_document("7782934451002") == doc

    raw = _example("SourceDocument")
    raw["scrubbed"] = False
    with pytest.raises(ContractViolation) as caught:
        store.write_source_document(raw)
    assert "scrubbed" in caught.value.errors[0]

    writers = [name for name in dir(Store)
               if name.startswith("write") or name.startswith("append") or name == "record_sources"]
    assert set(writers) == {
        "write_digest", "write_proposal", "write_run_manifest", "write_source_doc",
        "write_source_document", "write_theme", "write_theme_index", "write_watermark",
        "append_claims", "append_rejected", "record_sources",
    }
    assert Store.write_source_doc is Store.write_source_document


# ----------------------------------------------------------------- outputs


def test_proposal_and_digest_and_manifest(store: Store) -> None:
    path = store.write_proposal("THEME-0001", "2026-W37", RUN_ID, "Renewal invoices",
                                "The body the editor wrote.", "Two customers, one week.")
    assert path == store.path / "proposals" / "2026-W37" / "THEME-0001.md"
    proposals = store.read_proposals("2026-W37")
    assert proposals[0]["status"] == "proposed"
    assert proposals[0]["filed_issue_url"] is None
    assert "## Why it was proposed" in proposals[0]["body"]

    with pytest.raises(ContractViolation):
        store.write_proposal("NEW-1", "2026-W37", RUN_ID, "t", "b", "r")

    md, html = store.write_digest("2026-W37", "# digest\n", "<html></html>")
    assert md.read_text(encoding="utf-8") == "# digest\n"
    assert html.exists()

    manifest = _example("RunManifest")
    manifest_path = store.write_run_manifest(manifest)
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest


# ----------------------------------------------------------------- git


def test_commit_uses_the_contract_author_and_message_format(store: Store) -> None:
    theme = _theme()
    store.write_theme(theme, render_theme_body(theme, []))
    sha = store.commit("build 2026-W37 digest, 1 theme opened", RUN_ID)
    assert sha and len(sha) == 40

    log = subprocess.run(["git", "-C", str(store.path), "log", "--format=%H%n%an <%ae>%n%s"],
                         check=True, capture_output=True, text=True).stdout.strip().split("\n")
    assert len(log) == 3, log            # exactly one commit
    assert log[0] == sha
    assert log[1] == COMMIT_AUTHOR
    assert log[2] == "run 2026-09-14T07:00Z: build 2026-W37 digest, 1 theme opened"

    # An already prefixed message is not prefixed twice.
    (store.path / "themes" / "note.txt").write_text("x", encoding="utf-8")
    store.commit("run %s: second" % RUN_ID, RUN_ID)
    assert subprocess.run(["git", "-C", str(store.path), "log", "--format=%s", "-1"],
                          check=True, capture_output=True, text=True).stdout.strip() \
        == "run 2026-09-14T07:00Z: second"

def test_nothing_staged_is_a_skip_not_a_commit(store: Store) -> None:
    # No audit attached, because the run log lives inside the store and every commit event
    # written after a commit is itself an uncommitted change.
    store.attach_audit(None)
    assert store.commit("first", RUN_ID) is not None
    assert store.commit("second", RUN_ID) is None


def test_readonly_store_skips_the_commit_and_logs_it(store: Store,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIGEST_STORE_READONLY", "1")
    theme = _theme()
    store.write_theme(theme, render_theme_body(theme, []))
    assert store.commit("build", RUN_ID) is None
    events = [e for e in store.audit.events() if e["action"] == "commit"]
    assert events[-1]["outcome"] == "withheld"
    assert events[-1]["detail"]["reason"] == "DIGEST_STORE_READONLY=1"


def test_no_git_directory_is_also_a_skip(tmp_path: Path) -> None:
    bare = Store(tmp_path / "plain")
    (tmp_path / "plain").mkdir()
    bare.attach_audit(Audit(RUN_ID, tmp_path / "plain"))
    assert bare.commit("build", RUN_ID) is None
    assert bare.audit.events()[-1]["detail"]["reason"].startswith("no .git")


def test_clone_or_open_opens_a_path(store: Store) -> None:
    assert Store.clone_or_open(str(store.path)).path == store.path
    with pytest.raises(ContractViolation):
        Store.clone_or_open("https://example.invalid/store.git")


# ----------------------------------------------------------------- audit


def test_every_audit_line_validates_and_the_log_is_the_source_of_truth(store: Store) -> None:
    audit = store.audit
    audit.read("editor", "THEME-0001", stage="edit")
    audit.log(agent="gong_reader", action="call_model", stage="extract",
              target="gong:7782934451002", model_tier="extraction", model_id="a-model",
              prompt_hash="80ab0b6e75c1789d", tokens_in=3184, tokens_out=412, cost_usd=0.005244,
              detail={"attempt": 1})
    lines = store.audit.log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 2
    for line in lines:
        validate(json.loads(line), "AuditEvent")
    events = audit.events()
    assert events[0]["action"] == "read"
    assert all(e["run_id"] == RUN_ID for e in events)

    with pytest.raises(ContractViolation):
        audit.log(agent="x", action="not_an_action", stage="store", target="t")


def test_timed_records_duration_and_marks_an_exception(store: Store) -> None:
    audit = store.audit
    with audit.timed("scorer", "score", "score", "THEME-0001") as fields:
        fields["detail"] = {"themes": 1}
    event = audit.events()[-1]
    assert event["action"] == "score"
    assert event["detail"]["themes"] == 1
    assert isinstance(event["detail"]["duration_ms"], int)

    with pytest.raises(ValueError):
        with audit.timed("scorer", "score", "score", "THEME-0002"):
            raise ValueError("boom")
    event = audit.events()[-1]
    assert event["outcome"] == "error"
    assert event["detail"]["exception"] == "ValueError"


def test_a_scrub_event_carries_counts_only(store: Store) -> None:
    audit = store.audit
    audit.log(agent="scrubber", action="scrub", stage="scrub", target="gong:7782934451002",
              detail={"EMAIL": 2, "NAME": 1, "PHONE": 0, "ADDRESS": 0})
    assert audit.events()[-1]["detail"]["EMAIL"] == 2
    with pytest.raises(ContractViolation) as caught:
        audit.log(agent="scrubber", action="scrub", stage="scrub", target="gong:1",
                  detail={"EMAIL": "someone@example.invalid"})
    assert "counts only" in caught.value.errors[0]


def test_summary_math_and_the_manifest_it_feeds(store: Store) -> None:
    audit = store.audit
    audit.log(agent="connectors", action="read", stage="connect", target="gong:1")
    audit.log(agent="connectors", action="read", stage="connect", target="gong:2")
    audit.log(agent="connectors", action="withhold", stage="connect", target="case:500",
              outcome="withheld", detail={"count": 3})
    audit.log(agent="scrubber", action="scrub", stage="scrub", target="gong:1",
              detail={"EMAIL": 2, "PHONE": 1, "ADDRESS": 0, "NAME": 4})
    audit.log(agent="gong_reader", action="read", stage="extract", target="gong:1")
    audit.log(agent="gong_reader", action="call_model", stage="extract", target="gong:1",
              model_tier="extraction", model_id="a-model", prompt_hash="0123456789abcdef",
              tokens_in=1000, tokens_out=100, cache_read=50, cache_write=20, cost_usd=0.0015,
              detail={"claims_extracted": 2})
    audit.log(agent="editor", action="call_model", stage="edit", target="EditorProposal",
              model_tier="synthesis", model_id="b-model", prompt_hash="abcdef0123456789",
              tokens_in=4000, tokens_out=900, cost_usd=0.0425)
    audit.log(agent="verifier", action="verify", stage="verify", target="claim:1",
              outcome="rejected", detail={"reason_code": "citation_unresolved"})
    audit.log(agent="verifier", action="reject", stage="verify", target="claim:2",
              outcome="rejected", detail={"reason_code": "speaker_not_client", "count": 2})
    audit.log(agent="verifier", action="verify", stage="verify", target="run",
              detail={"claims_verified": 5})
    audit.log(agent="editor", action="propose", stage="propose", target="2026-W37/THEME-0001")
    audit.log(agent="gate", action="approve", stage="propose", target="THEME-0001")

    summary = audit.summary()
    counts = summary["counts"]
    assert set(counts) == set(COUNT_FIELDS)
    assert counts["sources_listed"] == 2
    assert counts["sources_read"] == 1
    assert counts["comments_withheld"] == 3
    assert counts["pii_redactions"] == 7
    assert counts["claims_extracted"] == 2
    assert counts["claims_verified"] == 5
    assert counts["claims_rejected"] == 3
    assert counts["proposals_written"] == 1
    assert counts["issues_filed"] == 1

    assert summary["pii_redactions_by_kind"] == {"EMAIL": 2, "PHONE": 1, "ADDRESS": 0, "NAME": 4}
    assert set(summary["rejected_by_reason"]) == set(REJECT_REASONS)
    assert summary["rejected_by_reason"]["citation_unresolved"] == 1
    assert summary["rejected_by_reason"]["speaker_not_client"] == 2

    usage = summary["usage"]
    assert [row["stage"] for row in usage["by_stage"]] == ["extract", "edit"]
    assert [row["tier"] for row in usage["by_tier"]] == ["extraction", "synthesis"]
    assert usage["total"]["calls"] == 2
    assert usage["total"]["tokens_in"] == 5000
    assert usage["total"]["tokens_out"] == 1000
    assert usage["total"]["cache_read"] == 50
    assert usage["total"]["cache_write"] == 20
    assert usage["total"]["cost_usd"] == pytest.approx(0.044)
    assert sum(row["cost_usd"] for row in usage["by_tier"]) == pytest.approx(0.044)
    assert set(summary["pii_redactions_by_kind"]) == set(PII_KINDS)

    manifest = _example("RunManifest")
    manifest.update({k: summary[k] for k in
                     ("counts", "rejected_by_reason", "pii_redactions_by_kind", "usage")})
    validate(manifest, "RunManifest")


# ----------------------------------------------------------------- small pure helpers


def test_source_ref_label_and_mmss() -> None:
    assert mmss(418000) == "06:58"
    assert mmss(3_600_000) == "60:00"      # minutes keep counting past 59
    assert source_ref_label(_example("Claim")) == "call 7782934451002 at 06:58"
    sfdc = {"source_ref": {"case_number": "00001042", "comment_id": "00a8W00000XfT2mQAF"}}
    assert source_ref_label(sfdc) == "case 00001042 comment 00a8W00000XfT2mQAF"
