"""Tests for the pipeline, the CLI and the eval runner.

Nothing here makes a model call. The one test that exercises the whole ingest path runs in
replay mode against an empty store, which is exactly the shape of the failure the contract
cares about: a missing recording is a hard stop with an exit code, not a silent live call.
"""
from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path

import pytest

from digest import eval as eval_module
from digest import pipeline
from digest.__main__ import build_parser, main
from digest.audit import Audit
from digest.contracts import validate
from digest.errors import EXIT_REPLAY_MISS

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- the calendar


def test_the_calendar_is_the_one_in_the_contract():
    assert len(pipeline.INGEST_DAYS) == 15
    assert pipeline.INGEST_DAYS[0] == "2026-09-07"
    assert pipeline.INGEST_DAYS[-1] == "2026-09-25"
    assert pipeline.WEEKS == ("2026-W37", "2026-W38", "2026-W39")
    for day in pipeline.INGEST_DAYS:
        assert datetime.date.fromisoformat(day).isoweekday() <= 5


def test_run_ids_follow_the_pinned_format():
    assert pipeline.ingest_run_id("2026-09-08") == "2026-09-08T06:00Z"
    assert pipeline.ingest_run_id(datetime.date(2026, 9, 11)) == "2026-09-11T06:00Z"
    assert pipeline.week_of("2026-09-08") == "2026-W37"
    assert pipeline.week_of("2026-09-25") == "2026-W39"


def test_claim_source_id_reads_either_variant():
    gong = {"source": "gong", "source_ref": {"call_id": "778", "speaker_id": "1"}}
    sfdc = {"source": "salesforce", "source_ref": {"case_id": "500abc", "comment_id": "0"}}
    assert pipeline.claim_source_id(gong) == "778"
    assert pipeline.claim_source_id(sfdc) == "500abc"


# --------------------------------------------------------------------------- stability maths


def test_assignment_pairs_and_top_three():
    themes = [
        {"theme_id": "THEME-0002", "score": 61, "evidence": ["aaaaaaaaaaaa"]},
        {"theme_id": "THEME-0001", "score": 74, "evidence": ["bbbbbbbbbbbb", "cccccccccccc"]},
        {"theme_id": "THEME-0003", "score": 61, "evidence": []},
        {"theme_id": "THEME-0004", "score": 10, "evidence": []},
    ]
    assert pipeline.assignment_pairs(themes) == {
        ("aaaaaaaaaaaa", "THEME-0002"),
        ("bbbbbbbbbbbb", "THEME-0001"),
        ("cccccccccccc", "THEME-0001"),
    }
    # score descending, then theme id ascending. The tiebreak is what makes a rerun stable.
    assert pipeline.top_three(themes) == ["THEME-0001", "THEME-0002", "THEME-0003"]


def test_jaccard_including_the_two_empty_sets():
    assert pipeline.jaccard(set(), set()) == 1.0
    assert pipeline.jaccard({1, 2}, {1, 2}) == 1.0
    assert pipeline.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert pipeline.jaccard({1}, set()) == 0.0


# --------------------------------------------------------------------------- the CLI


def test_globals_are_accepted_before_and_after_the_verb():
    parser = build_parser()
    before = parser.parse_args(["--mode", "record", "demo"])
    after = parser.parse_args(["demo", "--mode", "record"])
    assert before.mode == after.mode == "record"
    assert before.store == after.store


def test_swap_models_names_the_alternate_not_the_reference():
    args = build_parser().parse_args(
        ["swap", "--models", "config/models.cheap.yaml", "--week", "2026-W37"])
    assert args.alt_models == "config/models.cheap.yaml"
    assert args.models == "config/models.yaml"


def test_ingest_refuses_both_day_and_since_watermark(tmp_path, capsys):
    code = main(["ingest", "--day", "2026-09-08", "--since-watermark",
                 "--store", str(tmp_path)])
    assert code == 1
    assert "exactly one" in capsys.readouterr().err


def test_approve_without_yes_is_refused(tmp_path, capsys):
    code = main(["approve", "--theme", "THEME-0001", "--store", str(tmp_path)])
    assert code == 4
    assert "--yes required" in capsys.readouterr().err


def test_replay_against_an_empty_store_is_a_replay_miss(tmp_path, capsys):
    """The whole ingest path, offline, with no recordings: exit 3 and a usable message."""
    code = main(["ingest", "--day", "2026-09-08", "--mode", "replay",
                 "--store", str(tmp_path)])
    assert code == EXIT_REPLAY_MISS
    err = capsys.readouterr().err
    assert "replay miss" in err
    assert "--mode record" in err
    assert "gong_reader" in err or "sfdc_reader" in err
    # It got far enough to store the scrubbed sources before it needed a model.
    assert list((tmp_path / "sources").glob("*.json"))


# --------------------------------------------------------------------------- the manifest


def test_a_manifest_built_from_an_empty_audit_validates(tmp_path):
    audit = Audit("2026-09-08T06:00Z", tmp_path)
    manifest = pipeline._manifest("2026-09-08T06:00Z", "ingest", "2026-W37", "replay",
                                  "2026-09-08T06:00:00.000Z", audit)
    validate(manifest, "RunManifest")
    assert manifest["stability"] == {"computed": False, "jaccard": None,
                                     "top3_stable": None, "compared_run_id": None}
    assert manifest["counts"]["claims_verified"] == 0


def test_extra_counts_reach_the_manifest(tmp_path):
    audit = Audit("2026-09-14T07:00Z", tmp_path)
    manifest = pipeline._manifest("2026-09-14T07:00Z", "build", "2026-W37", "record",
                                  "2026-09-14T07:00:00.000Z", audit,
                                  extra_counts={"themes_opened": 8})
    validate(manifest, "RunManifest")
    assert manifest["counts"]["themes_opened"] == 8


# ------------------------------------------------------------------ the week's own numbers


def _ingest_manifest(store, day: str, week: str, counts: dict, cost: float) -> None:
    """One ingest run manifest on disk, with the counts and the cost this test needs."""
    run_id = pipeline.ingest_run_id(day)
    audit = Audit(run_id, store.path)
    manifest = pipeline._manifest(run_id, "ingest", week, "replay",
                                  "%sT06:00:00.000Z" % day, audit, extra_counts=counts)
    manifest["usage"]["by_tier"] = [{"tier": "extraction", "calls": 2, "tokens_in": 10,
                                     "tokens_out": 5, "cache_read": 0, "cache_write": 0,
                                     "cost_usd": cost}]
    manifest["usage"]["total"] = {"calls": 2, "tokens_in": 10, "tokens_out": 5,
                                  "cache_read": 0, "cache_write": 0, "cost_usd": cost}
    validate(manifest, "RunManifest")
    store.write_run_manifest(manifest)


def test_week_summary_adds_the_weeks_ingest_runs_to_this_build(tmp_path):
    """The build run alone reads nothing. The digest's run line has to report the week."""
    from digest.store import Store

    store = Store(tmp_path)
    _ingest_manifest(store, "2026-09-08", "2026-W37",
                     {"sources_read": 9, "comments_withheld": 4, "pii_redactions": 3,
                      "claims_extracted": 11, "claims_verified": 11}, 0.40)
    _ingest_manifest(store, "2026-09-09", "2026-W37",
                     {"sources_read": 7, "comments_withheld": 2, "pii_redactions": 1,
                      "claims_extracted": 7, "claims_verified": 7}, 0.30)
    # A different week's ingest run must not be counted.
    _ingest_manifest(store, "2026-09-21", "2026-W38",
                     {"sources_read": 1, "claims_verified": 1}, 0.10)
    store.record_sources("2026-09-08T06:00Z", [
        {"source": "gong", "source_id": "7782934451001", "account_id": "ACC-0001",
         "doc_type": "call", "occurred_at": "2026-09-08T15:00:00Z", "turn_count": 4,
         "withheld_comment_count": 0},
        {"source": "salesforce", "source_id": "5008W00002aQpLrQAK",
         "account_id": "ACC-0001", "doc_type": "case",
         "occurred_at": "2026-09-08T16:00:00Z", "turn_count": 3,
         "withheld_comment_count": 2},
    ])
    store.record_sources("2026-09-21T06:00Z", [
        {"source": "gong", "source_id": "7782934451099", "account_id": "ACC-0001",
         "doc_type": "call", "occurred_at": "2026-09-21T15:00:00Z", "turn_count": 2,
         "withheld_comment_count": 0},
    ])

    audit = Audit("2026-09-14T07:00Z", tmp_path)
    build = pipeline._manifest("2026-09-14T07:00Z", "build", "2026-W37", "replay",
                               "2026-09-14T07:00:00.000Z", audit,
                               extra_counts={"themes_appended": 0, "themes_opened": 10})
    build["usage"]["by_tier"] = [{"tier": "synthesis", "calls": 2, "tokens_in": 20,
                                  "tokens_out": 9, "cache_read": 0, "cache_write": 0,
                                  "cost_usd": 1.2187}]
    build["usage"]["total"] = {"calls": 2, "tokens_in": 20, "tokens_out": 9,
                               "cache_read": 0, "cache_write": 0, "cost_usd": 1.2187}

    summary = pipeline.week_summary("2026-W37", store, build)
    assert summary["ingest_run_ids"] == ["2026-09-08T06:00Z", "2026-09-09T06:00Z"]
    assert summary["counts"]["sources_read"] == 16
    assert summary["counts"]["comments_withheld"] == 6
    assert summary["counts"]["pii_redactions"] == 4
    assert summary["counts"]["claims_verified"] == 18
    assert summary["counts"]["themes_opened"] == 10
    assert summary["sources_by_doc_type"] == {"call": 1, "case": 1}
    assert summary["cost_usd"] == {"ingest": 0.7, "build": 1.2187, "total": 1.9187}
    assert summary["model_tiers"] == ["extraction", "synthesis"]

    # The build's own manifest is untouched by the aggregation.
    assert build["counts"]["sources_read"] == 0
    assert build["usage"]["total"]["cost_usd"] == 1.2187

    # And the renderers see the week through the manifest argument, without a new one.
    view = pipeline.week_run_line_view(build, summary)
    from digest.render.markdown import _run_line

    line = _run_line(view)
    assert "16 sources read (1 calls, 1 cases)" in line
    assert "6 private comments withheld, 4 PII redactions" in line
    assert "18 claims verified, 0 rejected, 0 themes appended, 10 opened" in line
    assert "cost $1.92 for the week ($1.22 this build)" in line
    assert "model tiers used: extraction, synthesis." in line


def test_week_summary_is_written_next_to_the_manifest_not_inside_it(tmp_path):
    from digest.store import Store

    store = Store(tmp_path)
    audit = Audit("2026-09-14T07:00Z", tmp_path)
    build = pipeline._manifest("2026-09-14T07:00Z", "build", "2026-W37", "replay",
                               "2026-09-14T07:00:00.000Z", audit)
    summary = pipeline.week_summary("2026-W37", store, build)
    path = pipeline.write_week_summary(store, "2026-09-14T07:00Z", summary)
    assert path == tmp_path / "runs" / "2026-09-14T07:00Z" / "week_summary.json"
    assert json.loads(path.read_text(encoding="utf-8"))["week"] == "2026-W37"
    # RunManifest is a closed schema, so the aggregate must not have leaked into it.
    validate(build, "RunManifest")
    assert "sources_by_doc_type" not in build


# --------------------------------------------------------------------------- negotiation


class _SchemaShapeRefuser:
    """A provider that declares native structured output and then refuses one schema shape.

    Exactly the behaviour the live seat shows for AnalystAnswer: a 400 on the tool input
    schema, not on the prompt. The second call is the fallback path.
    """

    name = "agent_sdk_seat"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[str] = []

    def capabilities(self):
        return {"native_structured": True, "strict_tools": False,
                "thinking_style": "adaptive", "effort": True}

    def translate_model_id(self, canonical_model_id):
        return canonical_model_id

    def complete(self, model_id, system, user, schema, params):
        from digest.errors import DigestError

        self.calls.append(user)
        if len(self.calls) == 1:
            raise DigestError(
                "agent_sdk_seat: the claude CLI failed (exit 1, terminal_reason api_error): "
                "API Error: 400 tools.0.custom.input_schema: input_schema does not support "
                "oneOf, allOf, or anyOf at the top level")
        return {"text": self.answer, "tokens_in": 10, "tokens_out": 20,
                "cache_read": 0, "cache_write": 0, "stop_reason": "end_turn"}


def test_a_refused_schema_shape_steps_down_one_negotiation_path(tmp_path):
    from digest.router import Router

    answer = json.dumps({
        "schema_version": "1.0.0", "question": "anything?", "answer": "Nothing on file.",
        "supported": False, "citations": [], "decline_reason": "the store has no theme on it",
    })
    provider = _SchemaShapeRefuser(answer)
    router = Router(REPO / "config" / "models.yaml", mode="live")
    router.set_provider(provider)
    audit = Audit("2026-09-28T08:00Z", tmp_path)

    result = router.complete("narrative", "sys", "ask", "AnalystAnswer",
                             run_id="2026-09-28T08:00Z", agent="analyst", audit=audit)

    assert result["data"]["supported"] is False
    assert len(provider.calls) == 2
    # The fallback is the router's own third path: the schema goes in the prompt text.
    assert "AnalystAnswer" in provider.calls[1] and "JSON Schema" in provider.calls[1]
    stepped = [e for e in audit.events()
               if (e.get("detail") or {}).get("negotiated_down_to") == "schema_in_prompt"]
    assert len(stepped) == 1
    # It must not look like a rejected claim in the manifest.
    assert audit.summary()["counts"]["claims_rejected"] == 0


def test_only_an_input_schema_refusal_triggers_the_step_down():
    from digest.errors import DigestError
    from digest.router import _is_schema_shape_rejection

    assert _is_schema_shape_rejection(DigestError(
        "API Error: 400 tools.0.custom.input_schema: input_schema does not support oneOf, "
        "allOf, or anyOf at the top level"))
    assert not _is_schema_shape_rejection(DigestError("API Error: 529 overloaded"))
    assert not _is_schema_shape_rejection(DigestError("the claude CLI timed out after 300s"))


# --------------------------------------------------------------------------- the store's git


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_commit_before_finds_the_state_a_run_started_from(tmp_path):
    repo = tmp_path / "store"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "agent@example.invalid")
    _git(repo, "config", "user.name", "bi-theme-digest-agent")
    shas = []
    for message in ("run 2026-09-11T06:00Z: ingest 2026-09-11",
                    "run 2026-09-14T07:00Z: build 2026-W37 digest",
                    "run 2026-09-14T06:00Z: ingest 2026-09-14"):
        (repo / "file.txt").write_text(message, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", message)
        shas.append(subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=True).stdout.strip())
    found = pipeline._commit_before(repo, "2026-09-14T07:00Z", "build")
    assert found == shas[0]
    # An unknown run falls back to HEAD, which is the right answer for a build that has
    # not committed yet: its working tree changes are exactly what HEAD does not carry.
    assert pipeline._commit_before(repo, "2026-09-21T07:00Z", "build") == shas[2]


# --------------------------------------------------------------------------- the eval runner


def test_the_golden_set_loads_and_every_checker_is_implemented():
    golden = eval_module.load_golden()
    assert golden["week"] == "2026-W37"
    assert len(golden["must_appear"]) == 5
    assert len(golden["must_not_appear"]) == 2
    assert len(golden["pii_must_not_appear"]) == 4
    names = {item["check"]["name"] for item in golden["structural"]}
    implemented = {
        "every_claim_cited_and_resolves", "t1_single_theme", "t2_aliases_both_names",
        "t3_prospect_ranks_below_customers", "no_pii_in_store", "rerun_same_theme_ids",
        "stale_flag_fires_w39",
    }
    assert names == implemented


def test_the_report_names_every_failure(tmp_path):
    result = {
        "results": [
            eval_module._result("S1", "structural", "citations resolve", True, "12 resolved"),
            eval_module._result("S7", "structural", "stale fires", False, "nothing is stale"),
        ],
        "passed": 1, "failed": 1, "total": 2, "pass_rate": 0.5, "stability": [],
    }
    report = eval_module.report_markdown(result)
    assert "1 of 2 assertions passed." in report
    assert "| S7 | structural | FAIL |" in report
    assert "Failed: S7" in report


def test_an_empty_store_fails_the_golden_set_rather_than_passing_it(tmp_path):
    (tmp_path / "themes").mkdir(parents=True)
    (tmp_path / "themes" / "_INDEX.md").write_text(
        "---\nschema_version: \"1.0.0\"\nowner: ai-operations\nsource: synthesized\n"
        "last_verified: 2026-09-14\nrun_id: 2026-09-14T07:00Z\n---\n\n# Theme index\n\n"
        "| id | title | product_area | status | score | accounts | evidence | "
        "last_updated_run | aliases |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
        encoding="utf-8")
    from digest.store import Store

    result = eval_module.run_eval(Store(tmp_path), context=None)
    assert result["failed"] > 0
    # The five must_appear claims cannot be there, so they must be reported as failures
    # rather than quietly skipped.
    failed = {row["id"] for row in result["results"] if not row["passed"]}
    assert {"T1a", "T1b", "T2a", "T2b", "T3"} <= failed


def test_the_recorded_corpus_index_maps_a_theme_key_to_its_sources():
    ids = eval_module._corpus_source_ids("dues_notice_deliverability")
    assert ids
    index = json.loads((REPO / "data" / "mock" / "index.json").read_text(encoding="utf-8"))
    expected = {e["id"] for e in index["entries"]
                if e.get("theme_key") == "dues_notice_deliverability"}
    assert ids == expected
