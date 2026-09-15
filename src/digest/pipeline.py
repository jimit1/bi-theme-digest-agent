"""The pipeline: the code that runs a day, a week and the whole demo end to end.

Everything here is glue. Not one decision in this file is made by a model: the agents
return validated documents and this module joins, counts, scores and writes them. That
split is the point of the whole prototype, so the seam is worth stating once: a model
call only ever happens inside `digest.router`, reached through a reader, the editor or
the analyst, and every one of those returns a document that a schema in `contracts/`
has already accepted.

Three things in here are decisions rather than plumbing, and each one is commented where
it happens:

1. The run calendar is simulated. `captured_at` on a claim is the ingest run's own
   timestamp and a theme's `last_verified` is the build run's date, so recency, quiet and
   stale are computed on the corpus calendar and the same demo produces the same numbers
   on any day somebody runs it.
2. Quiet and stale are flagged BEFORE the editor is called, so the editor reads the
   answer out of the index instead of doing date arithmetic itself.
3. Stability reruns the editor into a scratch copy of the store rather than against the
   real one, because a second opinion must not be able to change the first one.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from digest.agents.analyst.analyst import ask as analyst_ask
from digest.agents.editor.editor import build_date_for_week, run_editor, run_id_for_week
from digest.agents.readers import prompt_for as reader_prompt_for
from digest.agents.readers import read_source, render_user as reader_render_user
from digest.audit import Audit
from digest.connectors import AccountDirectory, GongConnector, McpToolClient, SalesforceConnector
from digest.contracts import validate
from digest.enrich import enrich
from digest.errors import ContractViolation, SchemaRejected
from digest.gate import write_proposals
from digest.pii.scrubber import load_names, scrub_document
from digest.providers import get_provider
from digest.render import render_html, render_markdown
from digest.router import Router, prompt_hash
from digest.score import rank, score
from digest.store import Store, render_theme_body
from digest.verify import verify_citations

__all__ = [
    "Context",
    "INGEST_DAYS",
    "WEEKS",
    "STALE_AFTER_DAYS",
    "ingest_day",
    "build_week",
    "demo",
    "ask",
    "week_of",
    "ingest_run_id",
    "claim_source_id",
    "assignment_pairs",
    "top_three",
    "jaccard",
]

# contracts/file_formats.md section 2. Fifteen ingestion days, Monday to Friday.
INGEST_DAYS: tuple[str, ...] = (
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
)

WEEKS: tuple[str, ...] = ("2026-W37", "2026-W38", "2026-W39")

# contracts/file_formats.md section 3, stated once there and quoted here.
STALE_AFTER_DAYS = 14

INGEST_SUFFIX = "T06:00Z"
AGENT = "pipeline"

SEAT_PROVIDER = "agent_sdk_seat"
SEAT_TIMEOUT_S = 1800.0


def _seat_timeout() -> float:
    """How long one live call may take. Thirty minutes, because a long synthesis turn is
    slow, not broken."""
    try:
        return float(os.environ.get("DIGEST_SEAT_TIMEOUT_S") or SEAT_TIMEOUT_S)
    except ValueError:
        return SEAT_TIMEOUT_S


# An ask and an approve are runs too, and a run id has no seconds, so they get their own
# hour after the last build rather than borrowing that build's directory.
ASK_RUN_ID = "2026-09-28T08:00Z"
APPROVE_RUN_ID = "2026-09-28T09:00Z"


# --------------------------------------------------------------------------- small helpers


def ingest_run_id(day: str | _dt.date) -> str:
    """The ingest run id for one calendar day."""
    value = day.isoformat() if isinstance(day, _dt.date) else str(day)
    return "%s%s" % (value, INGEST_SUFFIX)


def week_of(day: str | _dt.date) -> str:
    """The ISO week label a day belongs to."""
    value = day if isinstance(day, _dt.date) else _dt.date.fromisoformat(str(day))
    iso = value.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def claim_source_id(claim: dict[str, Any]) -> str:
    """The source document id a claim came from, whichever source it is."""
    ref = claim["source_ref"]
    return ref["call_id"] if claim["source"] == "gong" else ref["case_id"]


def _now() -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return stamp[:-3] + "Z"


def _run_timestamp(run_id: str) -> str:
    """A run id is an identifier with no seconds; documents want a full timestamp."""
    return "%s:00.000Z" % run_id[:-1]


def assignment_pairs(themes: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """The claim to theme assignment as a set of pairs, for the stability number."""
    out: set[tuple[str, str]] = set()
    for theme in themes:
        for claim_id in theme.get("evidence") or []:
            out.add((claim_id, theme["theme_id"]))
    return out


def top_three(themes: Iterable[dict[str, Any]]) -> list[str]:
    """The top three theme ids by score descending then id ascending."""
    ordered = sorted(themes, key=lambda t: (-int(t["score"]), t["theme_id"]))
    return [t["theme_id"] for t in ordered[:3]]


def jaccard(left: set[Any], right: set[Any]) -> float:
    """Intersection over union. Two empty sets are identical, which is 1.0."""
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


# --------------------------------------------------------------------------- the context


class Context:
    """Everything a run needs that is not the run itself: paths, mode and where to print.

    One object so `ingest_day`, `build_week` and `demo` take the same argument and the CLI
    builds it exactly once.
    """

    def __init__(self, store_path: str | os.PathLike[str],
                 models_path: str | os.PathLike[str],
                 mode: str = "replay",
                 responses_dir: str | os.PathLike[str] | None = None,
                 mock_dir: str | os.PathLike[str] | None = None,
                 printer: Callable[[str], None] | None = None) -> None:
        self.store_path = Path(store_path).resolve()
        self.models_path = Path(models_path).resolve()
        self.mode = mode
        self.responses_dir = Path(responses_dir).resolve() if responses_dir else None
        repo = Path(__file__).resolve().parents[2]
        self.mock_dir = Path(mock_dir).resolve() if mock_dir else (repo / "data" / "mock")
        self.printer = printer or print
        self.activate()

    def activate(self) -> "Context":
        """Point the process level environment at this context's paths.

        The router falls back to <DIGEST_STORE_PATH>/runs/<run_id>/responses when it is
        given no explicit directory, and `digest.enrich` reads DIGEST_MOCK_DIR. Both are
        re-stamped on every use rather than once at construction, because a stability or
        swap run builds a second context and the first one has to keep working after it.
        """
        os.environ["DIGEST_STORE_PATH"] = str(self.store_path)
        os.environ["DIGEST_MOCK_DIR"] = str(self.mock_dir)
        return self

    def say(self, line: str = "") -> None:
        """Print a progress line and flush it.

        Flushed because a run of this takes tens of minutes and its output is usually being
        watched through a pipe, where Python would otherwise buffer the whole thing and
        show nothing until the end.
        """
        self.printer(line)
        try:
            sys.stdout.flush()
        except (OSError, ValueError):  # pragma: no cover - a closed stream is not an error here
            pass

    def store(self) -> Store:
        self.activate()
        return Store(self.store_path)

    def router(self) -> Router:
        """A router for this context, with a timeout a synthesis call can actually finish in.

        The seat adapter defaults to five minutes, which is right for an extraction call and
        not enough for the editor: a high effort synthesis turn over a whole week of claims
        took longer than that on the first live run and came back as a transport timeout,
        which reads like a model failure and is not one. The tier map cannot carry this,
        because it is a property of the transport rather than of the tier, so the caller
        sets it. DIGEST_SEAT_TIMEOUT_S overrides it.
        """
        self.activate()
        router = Router(self.models_path, mode=self.mode, responses_dir=self.responses_dir)
        if self.mode != "replay" and router.provider_name() == SEAT_PROVIDER:
            router.set_provider(get_provider(SEAT_PROVIDER, timeout=_seat_timeout()))
        return router

    def with_overrides(self, *, store_path: str | os.PathLike[str] | None = None,
                       models_path: str | os.PathLike[str] | None = None,
                       responses_dir: str | os.PathLike[str] | None = None,
                       mode: str | None = None) -> "Context":
        """A copy with some paths swapped. Used by stability and by the model swap."""
        return Context(
            store_path=store_path or self.store_path,
            models_path=models_path or self.models_path,
            mode=mode or self.mode,
            responses_dir=responses_dir if responses_dir is not None else self.responses_dir,
            mock_dir=self.mock_dir,
            printer=self.printer,
        )

    # -- the two mock MCP servers ------------------------------------------

    def connectors(self, window_from: str, window_to: str, run_id: str):
        """Start both mock MCP servers for one window and return the two connectors.

        The window is the scoping control: the servers refuse a request that reaches
        outside it rather than trimming the answer, so a thin day is visibly a thin day.
        """
        self.activate()
        accounts = AccountDirectory.from_mock_dir(self.mock_dir)
        gong_client = McpToolClient.for_server(
            "gong", mock_dir=self.mock_dir, window_from=window_from, window_to=window_to)
        sfdc_client = McpToolClient.for_server(
            "salesforce", mock_dir=self.mock_dir, window_from=window_from, window_to=window_to)
        gong_client.start()
        sfdc_client.start()
        return (
            GongConnector(gong_client, accounts, ingest_run_id=run_id),
            SalesforceConnector(sfdc_client, accounts, ingest_run_id=run_id),
            gong_client,
            sfdc_client,
        )


# --------------------------------------------------------------------------- the manifest


def _manifest(run_id: str, run_type: str, week: str | None, mode: str,
              started_at: str, audit: Audit, exit_code: int = 0,
              stability: dict[str, Any] | None = None,
              extra_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Build a RunManifest from the audit log, which is the only source for the numbers.

    `summary()` derives counts, rejections, redactions and usage from the events
    themselves, so the manifest and the log cannot disagree. Everything added here is
    identity, not measurement.
    """
    summary = audit.summary()
    if extra_counts:
        for key, value in extra_counts.items():
            summary["counts"][key] = value
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "run_type": run_type,
        "week": week,
        "mode": mode,
        "started_at": started_at,
        "finished_at": _now(),
        "counts": summary["counts"],
        "rejected_by_reason": summary["rejected_by_reason"],
        "pii_redactions_by_kind": summary["pii_redactions_by_kind"],
        "usage": summary["usage"],
        "stability": stability or {
            "computed": False, "jaccard": None, "top3_stable": None, "compared_run_id": None,
        },
        "exit_code": exit_code,
    }
    validate(manifest, "RunManifest")
    return manifest


# ------------------------------------------------------------------- the week's own numbers

_USAGE_NUMBERS = ("calls", "tokens_in", "tokens_out", "cache_read", "cache_write", "cost_usd")


def _sum_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    """Add usage blocks together, keeping the by_stage and by_tier splits."""
    def rows(key: str, name: str) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for usage in usages:
            for row in usage.get(key) or []:
                into = merged.setdefault(row[name],
                                         dict({name: row[name]},
                                              **{n: 0 for n in _USAGE_NUMBERS}))
                for number in _USAGE_NUMBERS:
                    into[number] += row[number]
        for row in merged.values():
            row["cost_usd"] = round(row["cost_usd"], 6)
        return [merged[key] for key in sorted(merged)]

    total = {number: 0 for number in _USAGE_NUMBERS}
    for usage in usages:
        for number in _USAGE_NUMBERS:
            total[number] += usage["total"][number]
    total["cost_usd"] = round(total["cost_usd"], 6)
    return {"by_stage": rows("by_stage", "stage"), "by_tier": rows("by_tier", "tier"),
            "total": total}


def _ingest_manifests(store: Store, week: str) -> list[dict[str, Any]]:
    """Every ingest run manifest already written for this week, oldest first."""
    runs = store.path / "runs"
    if not runs.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for directory in sorted(runs.iterdir()):
        path = directory / "manifest.json"
        if not path.is_file():
            continue
        one = json.loads(path.read_text(encoding="utf-8"))
        if one.get("run_type") == "ingest" and one.get("week") == week:
            out.append(one)
    return out


def week_summary(week: str, store: Store, build_manifest: dict[str, Any]) -> dict[str, Any]:
    """What the week read, withheld, verified and cost: the ingest runs plus this build.

    A build run's own manifest honestly says zero sources and zero claims, because a build
    reads what earlier runs extracted. That is right for the manifest and useless in the
    digest, where the reader wants the week. So the week's ingest manifests are added up
    here, in code, off the files those runs already wrote, and handed to the renderers
    through the manifest argument. The RunManifest on disk keeps its own counts; this goes
    next to it as runs/<build_run_id>/week_summary.json so the metrics can cite exactly the
    numbers the digest shows.
    """
    manifests = _ingest_manifests(store, week)
    run_ids = [one["run_id"] for one in manifests]
    counts = {key: 0 for key in build_manifest["counts"]}
    rejected = {key: 0 for key in build_manifest["rejected_by_reason"]}
    redactions = {key: 0 for key in build_manifest["pii_redactions_by_kind"]}
    for one in manifests + [build_manifest]:
        for key in counts:
            counts[key] += one["counts"].get(key, 0)
        for key in rejected:
            rejected[key] += one["rejected_by_reason"].get(key, 0)
        for key in redactions:
            redactions[key] += one["pii_redactions_by_kind"].get(key, 0)
    usage = _sum_usage([one["usage"] for one in manifests] + [build_manifest["usage"]])
    by_doc_type = {"call": 0, "case": 0}
    for row in store.read_source_rows():
        if row["ingest_run"] in set(run_ids):
            by_doc_type[row["doc_type"]] = by_doc_type.get(row["doc_type"], 0) + 1
    ingest_cost = round(sum(one["usage"]["total"]["cost_usd"] for one in manifests), 6)
    return {
        "schema_version": "1.0.0",
        "week": week,
        "build_run_id": build_manifest["run_id"],
        "ingest_run_ids": run_ids,
        "counts": counts,
        "sources_by_doc_type": by_doc_type,
        "rejected_by_reason": rejected,
        "pii_redactions_by_kind": redactions,
        "cost_usd": {"ingest": ingest_cost,
                     "build": build_manifest["usage"]["total"]["cost_usd"],
                     "total": usage["total"]["cost_usd"]},
        "model_tiers": [row["tier"] for row in usage["by_tier"]],
        "usage": usage,
    }


def week_run_line_view(build_manifest: dict[str, Any],
                       summary: dict[str, Any]) -> dict[str, Any]:
    """The build manifest with the week's numbers in it, for the renderers.

    The renderers take a manifest and nothing else, and the digest's run line is a weekly
    line, so the weekly numbers travel in that argument rather than in a new one. This is
    never validated or written: `RunManifest` is a closed schema and the run on disk keeps
    its own counts.
    """
    view = json.loads(json.dumps(build_manifest))
    view["counts"] = summary["counts"]
    view["rejected_by_reason"] = summary["rejected_by_reason"]
    view["pii_redactions_by_kind"] = summary["pii_redactions_by_kind"]
    view["usage"] = summary["usage"]
    view["sources_by_doc_type"] = summary["sources_by_doc_type"]
    view["build_cost_usd"] = summary["cost_usd"]["build"]
    return view


def write_week_summary(store: Store, run_id: str, summary: dict[str, Any]) -> Path:
    """Alongside the manifest, not inside it."""
    path = store.path / "runs" / run_id / "week_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- ingest


def _existing_claim_ids(store: Store) -> set[str]:
    """Every claim id already in the store, for the duplicate check the contract pins.

    `verify_citations` dedupes within one reader output; check five in INTERFACES.md is
    across the whole store, and only the pipeline can see that far.
    """
    return {claim["claim_id"] for claim in store.read_claims()}


def ingest_day(day: str, context: Context) -> dict[str, Any]:
    """Ingest one calendar day: connect, scrub, store, read, verify, record, commit.

    Returns the RunManifest. Prints one summary line for the day.
    """
    started_at = _now()
    started_monotonic = time.monotonic()
    run_id = ingest_run_id(day)
    day_date = _dt.date.fromisoformat(day)
    store = context.store()
    audit = Audit(run_id, store.path)
    store.attach_audit(audit)
    router = context.router()
    names = load_names([
        context.mock_dir / "pii_names.json",
        context.mock_dir / "traps" / "pii_names.json",
    ])

    _last_run, watermark = store.read_watermark()
    if watermark is not None and watermark >= day_date:
        context.say("ingest %s: already ingested (watermark %s), nothing to do"
                    % (day, watermark.isoformat()))
        return _manifest(run_id, "ingest", week_of(day_date), context.mode, started_at, audit)

    # The server window starts the morning after the watermark, which is what makes this
    # incremental: a day already in the store is never read a second time.
    window_from = (watermark + _dt.timedelta(days=1)).isoformat() if watermark else day
    gong, sfdc, gong_client, sfdc_client = context.connectors(window_from, day, run_id)

    documents: list[dict[str, Any]] = []
    skipped = 0
    try:
        refs: list[dict[str, Any]] = []
        for connector in (gong, sfdc):
            refs.extend(connector.list_since(watermark, day_date))
        refs.sort(key=lambda r: (r["occurred_at"], r["source_id"]))

        for ref in refs:
            # Exactly one read event at stage connect per source listed: that rule is what
            # `Audit.summary()` counts sources_listed from, so nothing else may use it.
            audit.log(agent=AGENT, action="read", stage="connect", target=ref["source_id"],
                      detail={"source": ref["source"], "doc_type": ref["doc_type"],
                              "occurred_at": ref["occurred_at"],
                              "window_from": window_from, "window_to": day})
            connector = gong if ref["source"] == "gong" else sfdc
            raw = connector.fetch(ref["source_id"])

            # OD13: the connector emits scrubbed=true with zero counts and this stage is
            # what makes that true. Nothing unscrubbed is stored or shown to a model.
            document, counts = scrub_document(raw, names)
            audit.log(agent="scrubber", action="scrub", stage="scrub",
                      target=ref["source_id"], detail=dict(counts))

            withheld = int(document["meta"].get("withheld_comment_count") or 0)
            if withheld:
                audit.log(agent="connectors", action="withhold", stage="connect",
                          target=ref["source_id"], outcome="withheld",
                          detail={"count": withheld,
                                  "reason": "IsPublished false, never returned by the query"})

            if not document.get("account_id"):
                skipped += 1
                audit.log(agent=AGENT, action="reject", stage="connect",
                          target=ref["source_id"], outcome="rejected",
                          detail={"reason": "no account resolves for this document",
                                  "sources_skipped": 1, "count": 0})
                continue

            store.write_source_document(document)
            documents.append(document)

        account_ids = sorted({doc["account_id"] for doc in documents})
        enrichment: dict[str, dict[str, Any]] = {}
        if account_ids:
            with audit.timed("enrich", "read", "enrich", "accounts") as event:
                enrichment = enrich(account_ids, sfdc_client)
                event["detail"] = {"accounts": len(enrichment)}
    finally:
        gong_client.close()
        sfdc_client.close()

    seen = _existing_claim_ids(store)
    accepted_all: list[dict[str, Any]] = []
    rejected_all: list[dict[str, Any]] = []
    extracted_total = 0

    for document in documents:
        source_id = document["source_id"]
        account = {
            "account_id": document["account_id"],
            "account_name": document["account_name"],
            "account_type": enrichment[document["account_id"]]["account_type"],
        }
        system, _template = reader_prompt_for(document["source"])
        hashed = prompt_hash(system, reader_render_user(document), "ReaderOutput")

        try:
            reader_output = read_source(document, router, audit)
        except SchemaRejected as exc:
            # The router already logged the rejection. The pipeline records it as data.
            rejected = {
                "schema_version": "1.0.0", "run_id": run_id, "source": document["source"],
                "source_id": source_id, "reason_code": "schema_invalid",
                "reason": ("reader output failed %s twice: %s"
                           % (exc.schema_name, "; ".join(exc.errors)))[:500],
                "raw": {"errors": exc.errors[:20]},
            }
            validate(rejected, "RejectedClaim")
            rejected_all.append(rejected)
            continue

        extracted = len(reader_output.get("claims") or [])
        extracted_total += extracted
        accepted, rejected = verify_citations(
            reader_output, document, run_id, account,
            prompt_hash=hashed, model_tier="extraction")

        kept: list[dict[str, Any]] = []
        for claim in accepted:
            # OD21: the pipeline simulates a nightly run on a corpus date, so the claim is
            # stamped with the run's own timestamp rather than the wall clock. Without this
            # every recency number would be "today" and the stale rule could never fire.
            claim["captured_at"] = _run_timestamp(run_id)
            validate(claim, "Claim")
            if claim["claim_id"] in seen:
                rejected.append({
                    "schema_version": "1.0.0", "run_id": run_id, "source": document["source"],
                    "source_id": source_id, "reason_code": "duplicate",
                    "reason": "claim_id %s is already in the store" % claim["claim_id"],
                    "raw": {"claim_id": claim["claim_id"]},
                })
                continue
            seen.add(claim["claim_id"])
            kept.append(claim)

        for item in rejected:
            audit.log(agent="verifier", action="verify", stage="verify", target=source_id,
                      outcome="rejected",
                      detail={"reason_code": item["reason_code"], "count": 1})
        audit.log(agent="verifier", action="verify", stage="verify", target=source_id,
                  detail={"claims_extracted": extracted, "claims_verified": len(kept)})

        accepted_all.extend(kept)
        rejected_all.extend(rejected)

    if accepted_all:
        store.append_claims(run_id, accepted_all)
    if rejected_all:
        store.append_rejected(run_id, rejected_all)

    store.record_sources(run_id, documents)
    store.write_watermark(run_id, day_date)

    by_reason: dict[str, int] = {}
    for item in rejected_all:
        by_reason[item["reason_code"]] = by_reason.get(item["reason_code"], 0) + 1

    manifest = _manifest(run_id, "ingest", week_of(day_date), context.mode, started_at, audit,
                         extra_counts={"sources_skipped": skipped})
    store.write_run_manifest(manifest)
    store.commit("run %s: ingest %s, %d sources, %d claims"
                 % (run_id, day, len(documents), len(accepted_all)), run_id)

    counts = manifest["counts"]
    reasons = ", ".join("%s %d" % (k, v) for k, v in sorted(by_reason.items())) or "none"
    context.say(
        "ingest %s: %d sources listed, %d read, %d skipped, %d comments withheld, "
        "%d redactions, %d claims extracted, %d verified, %d rejected (%s), %.1fs"
        % (day, counts["sources_listed"], counts["sources_read"], skipped,
           counts["comments_withheld"], counts["pii_redactions"], extracted_total,
           len(accepted_all), len(rejected_all), reasons,
           time.monotonic() - started_monotonic))
    return manifest


# --------------------------------------------------------------------------- build


def _theme_last_evidence_at(store: Store, claims_by_id: dict[str, dict[str, Any]],
                            evidence: list[str]) -> str:
    """The newest source document timestamp behind a theme's evidence.

    Read off the source documents rather than the wall clock, so a theme's age is the age
    of what it is made of.
    """
    stamps: list[str] = []
    for claim_id in evidence:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        try:
            stamps.append(store.read_source_document(claim_source_id(claim))["occurred_at"])
        except ContractViolation:
            stamps.append(claim["captured_at"])
    return max(stamps) if stamps else _run_timestamp("2026-09-14T07:00Z")


def _apply_score(theme: dict[str, Any], enrichment: dict[str, dict[str, Any]],
                 claims_by_id: dict[str, dict[str, Any]], as_of: _dt.date,
                 audit: Audit) -> dict[str, Any]:
    """Score a theme in code and set the quiet and stale flags from the same number.

    contracts/file_formats.md section 3 defines the horizon as fourteen days and defines
    stale against `last_verified`. `last_verified` is the date of the build that last
    touched the theme, which at the 2026-09-28 build is exactly fourteen days old for the
    theme that has had no evidence since week 37: the boundary falls one day short of the
    behaviour OD8 pins. So the age used here is the age of the newest EVIDENCE, which is
    `score_inputs.recency_days` and is the same number the quiet rule already uses. One
    horizon, one measurement, both flags.
    """
    value, inputs = score(theme, enrichment, claims_by_id, as_of)
    theme["score"] = value
    theme["score_inputs"] = dict(inputs)
    theme["last_evidence_at"] = theme.get("last_evidence_at") or _run_timestamp(theme["run_id"])
    aged = int(inputs["recency_days"]) > STALE_AFTER_DAYS
    if theme["status"] != "filed":
        theme["status"] = "quiet" if aged else "open"
    theme["stale"] = aged
    theme["stale_reason"] = (
        "newest evidence is %d days old, past the fourteen day verify horizon"
        % inputs["recency_days"]) if aged else None
    audit.log(agent="scorer", action="score", stage="score", target=theme["theme_id"],
              detail={"score": value, "recency_days": int(inputs["recency_days"]),
                      "status": theme["status"], "stale": theme["stale"]})
    return theme


def _flag_quiet_and_stale(store: Store, enrichment: dict[str, dict[str, Any]],
                          claims_by_id: dict[str, dict[str, Any]], as_of: _dt.date,
                          audit: Audit) -> tuple[int, int]:
    """Rescore every theme already on disk, before the editor reads the index.

    Code decides quiet and stale and the editor is told the answer. A model asked to do
    date arithmetic across twenty themes will eventually get one wrong and nobody will
    notice. `last_updated_run` is deliberately not touched: a theme that received nothing
    this week must keep ageing.
    """
    quiet = stale = 0
    for line in store.read_theme_index():
        theme, body = store.read_theme(line["theme_id"])
        _apply_score(theme, enrichment, claims_by_id, as_of, audit)
        quiet += 1 if theme["status"] == "quiet" else 0
        stale += 1 if theme["stale"] else 0
        store.write_theme(theme, body)
    return quiet, stale


def _rationale_for(proposal: dict[str, Any], ref: str, fallback: str) -> str:
    for item in proposal.get("theme_rationales") or []:
        if item["theme_id_or_placeholder"] == ref:
            # The theme file caps a rationale at 900 characters; the editor's schema is
            # looser. Truncating a display field is a rendering decision, not a validation
            # bypass: the full text is in the recorded response either way.
            return item["rationale"][:900]
    return fallback[:900]


def _digest_frontmatter(week: str, run_id: str, as_of: _dt.date) -> str:
    """The five StoreFrontmatter keys plus week and run_id, per file_formats.md section 11.

    The renderer produces the document body and the store writes bytes, so neither of them
    owns this block; the pipeline is the one that knows which run wrote the file.
    """
    return (
        "---\n"
        'schema_version: "1.0.0"\n'
        "owner: ai-operations\n"
        "source: synthesized\n"
        "last_verified: %s\n"
        "run_id: %s\n"
        "week: %s\n"
        "---\n\n" % (as_of.isoformat(), run_id, week)
    )


def build_week(week: str, context: Context, stability: bool = False) -> dict[str, Any]:
    """Build one week's digest. Returns the RunManifest."""
    started_at = _now()
    started_monotonic = time.monotonic()
    run_id = run_id_for_week(week)
    as_of = build_date_for_week(week)
    store = context.store()
    if stability and (store.path / "runs" / run_id / "manifest.json").is_file():
        # The week is already built. Building it again would append this week's claims to
        # the themes they already opened and write a history that never happened, so the
        # second opinion is taken in a scratch copy instead. See measure_stability.
        measure_stability(week, context)
        return json.loads((store.path / "runs" / run_id / "manifest.json")
                          .read_text(encoding="utf-8"))
    audit = Audit(run_id, store.path)
    store.attach_audit(audit)
    router = context.router()

    week_claims = store.read_claims(week=week)
    all_claims = store.read_claims()
    claims_by_id = {claim["claim_id"]: claim for claim in all_claims}

    # Enrich every account that has a claim this week (validate_proposal insists on it) and
    # every account already carried by a theme, because scoring needs all of them.
    account_ids = {claim["account_id"] for claim in week_claims}
    for line in store.read_theme_index():
        theme, _body = store.read_theme(line["theme_id"])
        account_ids.update(theme.get("accounts") or [])
    window_from, window_to = INGEST_DAYS[0], INGEST_DAYS[-1]
    _gong, _sfdc, gong_client, sfdc_client = context.connectors(window_from, window_to, run_id)
    try:
        with audit.timed("enrich", "read", "enrich", "accounts") as event:
            enrichment = enrich(sorted(account_ids), sfdc_client)
            event["detail"] = {"accounts": len(enrichment)}
    finally:
        gong_client.close()
        sfdc_client.close()

    quiet_before, stale_before = _flag_quiet_and_stale(
        store, enrichment, claims_by_id, as_of, audit)

    proposal = run_editor(week, week_claims, enrichment, store, router, audit)

    placeholders = [entry["placeholder"] for entry in proposal.get("new_themes") or []]
    theme_id_map = store.allocate_theme_ids(placeholders)
    new_by_placeholder = {e["placeholder"]: e for e in proposal.get("new_themes") or []}
    proposed_refs = {entry["theme_id_or_placeholder"] for entry in proposal.get("file_proposals") or []}

    assignments: dict[str, list[str]] = {}
    actions: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for decision in proposal["decisions"]:
        ref = decision["theme_id"]
        target = theme_id_map.get(ref, ref)
        assignments.setdefault(target, []).append(decision["claim_id"])
        actions[target] = decision["action"]
        reasons.setdefault(target, decision["reason"])

    appended = opened = 0
    touched: list[dict[str, Any]] = []
    for theme_id in sorted(assignments):
        claim_ids = assignments[theme_id]
        placeholder = next((p for p, t in theme_id_map.items() if t == theme_id), None)
        if placeholder is not None:
            entry = new_by_placeholder[placeholder]
            theme = {
                "schema_version": "1.0.0",
                "theme_id": theme_id,
                "title": entry["title"],
                "aliases": list(entry.get("aliases") or []),
                "product_area": entry["product_area"],
                "status": "open",
                "owner": "ai-operations",
                "source": "synthesized",
                "last_verified": as_of.isoformat(),
                "run_id": run_id,
                "created_run": run_id,
                "last_updated_run": run_id,
                "accounts": [],
                "evidence": [],
                "score": 0,
                "score_inputs": {},
                "rationale": _rationale_for(proposal, placeholder, entry["rationale_seed"]),
                "stale": False,
                "stale_reason": None,
                "last_evidence_at": _run_timestamp(run_id),
                "proposal_id": None,
                "filed_issue_url": None,
            }
            opened += 1
            reference = placeholder
        else:
            theme, _body = store.read_theme(theme_id)
            theme["rationale"] = _rationale_for(proposal, theme_id, theme["rationale"])
            theme["last_updated_run"] = run_id
            theme["run_id"] = run_id
            theme["last_verified"] = as_of.isoformat()
            appended += 1
            reference = theme_id

        evidence = list(theme.get("evidence") or [])
        for claim_id in claim_ids:
            if claim_id not in evidence:
                evidence.append(claim_id)
        theme["evidence"] = evidence
        theme["accounts"] = sorted({claims_by_id[c]["account_id"] for c in evidence})
        theme["last_evidence_at"] = _theme_last_evidence_at(store, claims_by_id, evidence)
        if reference in proposed_refs:
            theme["proposal_id"] = "%s/%s" % (week, theme_id)
        _apply_score(theme, enrichment, claims_by_id, as_of, audit)
        store.write_theme(theme, render_theme_body(theme, [claims_by_id[c] for c in evidence]))
        touched.append(theme)
        context.say("  %s %s %s: %s"
                    % ("appended to" if placeholder is None else "opened  ",
                       theme_id, theme["title"], reasons.get(theme_id, "")[:160]))

    store.rebuild_index(run_id)

    # Proposals are written before the digest is rendered, because the digest's
    # "Proposed for filing" section reads them back off disk.
    written = write_proposals(week, run_id, proposal, theme_id_map, store)
    for path in written:
        audit.log(agent="gate", action="propose", stage="propose", target=path.name)

    themes: list[dict[str, Any]] = []
    for line in store.read_theme_index():
        theme, _body = store.read_theme(line["theme_id"])
        themes.append(theme)
    themes_ranked = rank(themes)

    digest = json.loads(json.dumps(proposal["digest"]))
    for section in digest.get("sections") or []:
        ref = section["theme_id_or_placeholder"]
        section["theme_id_or_placeholder"] = theme_id_map.get(ref, ref)
    for item in digest.get("reconciliations") or []:
        ref = item["theme_id_or_placeholder"]
        item["theme_id_or_placeholder"] = theme_id_map.get(ref, ref)

    quiet_now = sum(1 for t in themes if t["status"] == "quiet")
    stale_now = sum(1 for t in themes if t["stale"])
    manifest = _manifest(run_id, "build", week, context.mode, started_at, audit,
                         extra_counts={"themes_appended": appended, "themes_opened": opened,
                                       "themes_quiet": quiet_now, "themes_stale": stale_now})

    # The run line is the week's line, so the renderers get the week's numbers: this build
    # plus the ingest runs that fed it. The manifest itself is untouched.
    summary = week_summary(week, store, manifest)
    week_view = week_run_line_view(manifest, summary)
    with audit.timed("renderer", "write", "render", "digests/%s" % week):
        md = render_markdown(week, digest, themes_ranked, claims_by_id, week_view, store)
        html = render_html(week, digest, themes_ranked, claims_by_id, week_view, store)
    md_path, html_path = store.write_digest(week, _digest_frontmatter(week, run_id, as_of) + md,
                                            html)

    stability_block = {"computed": False, "jaccard": None, "top3_stable": None,
                       "compared_run_id": None}
    if stability:
        stability_block = _stability(week, context, themes, run_id,
                                     {c["claim_id"] for c in week_claims})

    manifest = _manifest(run_id, "build", week, context.mode, started_at, audit,
                         stability=contract_stability(stability_block),
                         extra_counts={"themes_appended": appended, "themes_opened": opened,
                                       "themes_quiet": quiet_now, "themes_stale": stale_now})
    store.write_run_manifest(manifest)
    # Written from the same summary the digest was rendered from, so the file and the run
    # line can never drift apart.
    write_week_summary(store, run_id, summary)
    store.commit("run %s: build %s digest, %d themes appended, %d opened"
                 % (run_id, week, appended, opened), run_id)

    context.say(
        "build %s: %d themes appended, %d opened, %d quiet (%d before), %d stale (%d before), "
        "%d proposals, cost $%.4f, %.1fs"
        % (week, appended, opened, quiet_now, quiet_before, stale_now, stale_before,
           len(written), manifest["usage"]["total"]["cost_usd"],
           time.monotonic() - started_monotonic))
    context.say("  %s" % md_path)
    context.say("  %s" % html_path)
    if stability_block["computed"]:
        context.say("  stability: jaccard %.3f (labelled %.3f), top three stable %s%s"
                    % (stability_block["jaccard"], stability_block["labelled_jaccard"],
                       stability_block["top3_stable"],
                       "" if context.mode != "replay" else
                       " (both sides replay the same recordings here, so this is trivially "
                       "1.0; the live number is the one worth reporting)"))
    return manifest


STABILITY_RESPONSES = "responses-stability"


def rerun_week(week: str, context: Context, dest: Path, *,
               models_path: Path | None = None, mode: str | None = None,
               responses_dir: Path | None = None) -> tuple[Store, dict[str, Any]]:
    """Run one week's build again from the state it originally started from.

    The scratch store is cloned from the commit the real build started from, so the second
    run reads the same index the first one did. It writes only into `dest`, so a second
    opinion can never change the first one. Shared by the stability check and the model
    swap, because they are the same experiment with a different variable.
    """
    run_id = run_id_for_week(week)
    _copy_store_before(context.store_path, dest, run_id)
    side = context.with_overrides(store_path=dest, models_path=models_path,
                                  mode=mode, responses_dir=responses_dir)
    side.printer = lambda _line: None
    manifest = build_week(week, side, stability=False)
    context.activate()
    return Store(dest), manifest


def _themes_of(store: Store) -> list[dict[str, Any]]:
    return [store.read_theme(line["theme_id"])[0] for line in store.read_theme_index()]


def _restrict(pairs: set[tuple[str, str]], claim_ids: set[str]) -> set[tuple[str, str]]:
    """Only this week's claims. A later week's evidence is not this run's opinion."""
    return {pair for pair in pairs if pair[0] in claim_ids}


def _stability(week: str, context: Context, themes: list[dict[str, Any]],
               run_id: str, week_claim_ids: set[str]) -> dict[str, Any]:
    """Second opinion on a build that has just happened, against what it just wrote."""
    responses = (context.responses_dir if context.mode == "replay" else
                 context.store_path / "runs" / run_id / STABILITY_RESPONSES)
    with tempfile.TemporaryDirectory(prefix="digest-stability-") as tmp:
        second_store, _manifest = rerun_week(week, context, Path(tmp) / "store",
                                             responses_dir=responses)
        second = _themes_of(second_store)
        return _compare(themes, second, run_id, week_claim_ids)


def co_assignment(themes: Iterable[dict[str, Any]], claim_ids: set[str]) -> set[tuple[str, str]]:
    """Every unordered pair of claims the run put on the same theme.

    This is the claim to theme assignment with the labels taken out. Two runs that group the
    same claims the same way agree here even when the ids they allocated differ, and on a
    cold start week the ids are arbitrary: both runs start from an empty index and number
    their new themes in the order they happen to list them. Measuring the labels instead
    would score a pure renumbering as total disagreement, which is not what anybody means by
    "did it put the same things together".
    """
    out: set[tuple[str, str]] = set()
    for theme in themes:
        members = sorted(c for c in (theme.get("evidence") or []) if c in claim_ids)
        for index, left in enumerate(members):
            for right in members[index + 1:]:
                out.add((left, right))
    return out


def contract_stability(block: dict[str, Any]) -> dict[str, Any]:
    """Just the four keys RunManifest.stability allows. The extra numbers are for the run
    output and the write up, and the schema is closed on purpose."""
    return {key: block[key] for key in
            ("computed", "jaccard", "top3_stable", "compared_run_id")}


def _compare(first: list[dict[str, Any]], second: list[dict[str, Any]], run_id: str,
             week_claim_ids: set[str]) -> dict[str, Any]:
    """The stability block, plus the two numbers behind it kept as separate keys.

    `jaccard` is the label independent one, because that is the question the golden set is
    asking. `labelled_jaccard` is the strict pair overlap including the allocated theme id,
    which is the harsher number and is reported alongside rather than hidden.
    """
    left = _restrict(assignment_pairs(first), week_claim_ids)
    right = _restrict(assignment_pairs(second), week_claim_ids)
    return {
        "computed": True,
        "jaccard": round(jaccard(co_assignment(first, week_claim_ids),
                                 co_assignment(second, week_claim_ids)), 6),
        "top3_stable": top_three(second) == top_three(first),
        "compared_run_id": run_id,
        "labelled_jaccard": round(jaccard(left, right), 6),
        "themes_first": len(first),
        "themes_second": len(second),
    }


def measure_stability(week: str, context: Context) -> dict[str, Any]:
    """Second opinion on a build that is already committed, without rebuilding it.

    Rerunning the real build over a store that already carries its themes would turn eight
    opened themes into eight appends and write a history that never happened. So both sides
    are run from the pre build commit into scratch copies: the reference replayed from its
    own committed recordings, which is free and reproduces exactly what was committed, and
    the second opinion recorded live into its own directory. Two runs, same input, one
    variable: the model's own non determinism.
    """
    run_id = run_id_for_week(week)
    store = context.store()
    week_claim_ids = {c["claim_id"] for c in store.read_claims(week=week)}
    reference_responses = context.store_path / "runs" / run_id / "responses"
    second_responses = context.store_path / "runs" / run_id / STABILITY_RESPONSES

    with tempfile.TemporaryDirectory(prefix="digest-stability-") as tmp:
        root = Path(tmp)
        first_store, first_manifest = rerun_week(
            week, context, root / "first", mode="replay",
            responses_dir=reference_responses)
        second_store, second_manifest = rerun_week(
            week, context, root / "second", mode=context.mode,
            responses_dir=second_responses)
        block = _compare(_themes_of(first_store), _themes_of(second_store), run_id,
                         week_claim_ids)

    manifest_path = store.path / "runs" / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stability"] = contract_stability(block)
    validate(manifest, "RunManifest")
    store.write_run_manifest(manifest)
    store.commit("run %s: stability for %s, jaccard %.3f" % (run_id, week, block["jaccard"]),
                 run_id)
    context.say(
        "stability %s: claim co-assignment jaccard %.3f, with theme ids %.3f, "
        "top three %s, %d themes against %d"
        % (week, block["jaccard"], block["labelled_jaccard"],
           "stable" if block["top3_stable"] else "CHANGED",
           block["themes_second"], block["themes_first"]))
    context.say(
        "  second opinion cost $%.4f against the reference run's $%.4f. Both sides were run "
        "from the commit the build started from, against separate recordings, so this is a "
        "real second opinion whichever mode it is replayed in."
        % (second_manifest["usage"]["total"]["cost_usd"],
           first_manifest["usage"]["total"]["cost_usd"]))
    return block


def _copy_store_before(store_path: Path, dest: Path, run_id: str) -> Path:
    """A copy of the store as it stood before the run `run_id` committed.

    Uses the store's own git history, which is what it is for: one commit per run means
    "the state this run started from" is the parent of this run's commit.
    """
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = _commit_before(store_path, run_id, "build")
    if sha is None:
        shutil.copytree(store_path, dest, ignore=shutil.ignore_patterns(".git"))
        subprocess.run(["git", "init", "-q"], cwd=dest, check=False, capture_output=True)
        return dest
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(store_path), str(dest)],
                   check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", sha],
                   check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", "-b", "scratch"],
                   check=True, capture_output=True, text=True)
    return dest


def _commit_before(store_path: Path, run_id: str, verb: str) -> str | None:
    """The sha of the commit immediately before `run <run_id>: <verb>`, or None."""
    import subprocess

    if not (store_path / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(store_path), "log", "--format=%H%x1f%s"],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    rows = [line.split("\x1f", 1) for line in proc.stdout.splitlines() if "\x1f" in line]
    prefix = "run %s: %s" % (run_id, verb)
    for position, (_sha, subject) in enumerate(rows):
        if subject.startswith(prefix):
            if position + 1 < len(rows):
                return rows[position + 1][0]
            return None
    return rows[0][0] if rows else None


# --------------------------------------------------------------------------- ask and demo


def ask(question: str, context: Context) -> dict[str, Any]:
    """One analyst question against the theme store. Returns a validated AnalystAnswer.

    An ask gets its own run id, an hour after the last build, so its recordings and its
    run log sit in their own directory instead of inside a build's.
    """
    run_id = ASK_RUN_ID
    store = context.store()
    audit = Audit(run_id, store.path)
    router = context.router()
    answer = analyst_ask(question, store, router, audit)
    context.say(answer["answer"])
    if answer["supported"]:
        for citation in answer["citations"]:
            context.say("  [%s] %s" % (citation.get("theme_id"), citation.get("claim_id")))
    else:
        context.say("  unsupported: %s" % answer["decline_reason"])
    # An ask leaves a run log and, in record mode, a recording. Both belong in the store's
    # history: the question a person asked and the answer they were given is exactly the
    # kind of thing an audit trail is for.
    store.commit("run %s: ask, %s" % (run_id, "answered" if answer["supported"]
                                      else "declined"), run_id)
    return answer


def demo(context: Context) -> dict[str, Any]:
    """Every ingest day, then every week, in order. The only command a reader has to run."""
    started = time.monotonic()
    for day in INGEST_DAYS:
        ingest_day(day, context)
    paths: list[str] = []
    for week in WEEKS:
        build_week(week, context)
        paths.append(str(context.store_path / "digests" / ("%s.md" % week)))
    store = context.store()
    commits = _commit_count(store.path)
    context.say("")
    context.say("demo complete in %.1fs, mode %s" % (time.monotonic() - started, context.mode))
    for path in paths:
        context.say("  %s" % path)
    context.say("  store commits: %s" % commits)
    return {"digests": paths, "commits": commits, "mode": context.mode}


def _commit_count(store_path: Path) -> int | None:
    import subprocess

    if not (store_path / ".git").exists():
        return None
    proc = subprocess.run(["git", "-C", str(store_path), "rev-list", "--count", "HEAD"],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    return int(proc.stdout.strip() or 0)
