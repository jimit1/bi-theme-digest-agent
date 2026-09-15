"""The run log: one validated AuditEvent per line, including reads.

Every action any part of this pipeline takes lands in `runs/<run_id>/run.log.jsonl` in the
store repository, one JSON document per line, flushed as it happens so a crashed run still
leaves a readable trail. Reads are logged as well as writes, because "what did it touch"
has to be a query rather than a guess.

Two rules worth stating because they are enforced here rather than promised in prose:

1. Nothing is logged that has not validated against `AuditEvent.schema.json`. The log is
   not a place to be lenient: an event that does not validate raises ContractViolation.
2. A `scrub` event carries counts, never values. `log` rejects a scrub detail that holds
   anything but integers, so a redacted email address cannot be smuggled into the audit
   trail by a well meaning caller. The id of what was scrubbed goes in `target`, which is
   what that field is for.

`summary()` derives the `counts`, `rejected_by_reason`, `pii_redactions_by_kind` and
`usage` blocks of a RunManifest from the events themselves, so the manifest and the log
can never disagree.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

from digest.contracts import schema_version, validate
from digest.errors import ContractViolation

__all__ = [
    "Audit",
    "STAGES",
    "TIERS",
    "ACTIONS",
    "OUTCOMES",
    "PII_KINDS",
    "REJECT_REASONS",
    "COUNT_FIELDS",
]

# The fixed ten. file_formats.md section 14. Nothing else is a stage.
STAGES: tuple[str, ...] = (
    "connect",
    "scrub",
    "extract",
    "verify",
    "enrich",
    "edit",
    "score",
    "render",
    "store",
    "propose",
)

TIERS: tuple[str, ...] = ("extraction", "synthesis", "narrative")

ACTIONS: tuple[str, ...] = (
    "read",
    "call_model",
    "validate",
    "reject",
    "verify",
    "scrub",
    "write",
    "commit",
    "withhold",
    "propose",
    "approve",
    "score",
)

OUTCOMES: tuple[str, ...] = ("ok", "rejected", "error", "withheld")

PII_KINDS: tuple[str, ...] = ("EMAIL", "PHONE", "ADDRESS", "NAME")

REJECT_REASONS: tuple[str, ...] = (
    "schema_invalid",
    "citation_unresolved",
    "speaker_not_client",
    "duplicate",
    "window_violation",
)

COUNT_FIELDS: tuple[str, ...] = (
    "sources_listed",
    "sources_read",
    "sources_skipped",
    "comments_withheld",
    "pii_redactions",
    "claims_extracted",
    "claims_verified",
    "claims_rejected",
    "themes_appended",
    "themes_opened",
    "themes_quiet",
    "themes_stale",
    "proposals_written",
    "issues_filed",
)

# Keys a scrub detail may carry that are not counts. Everything else must be an integer.
_SCRUB_ALLOWED_NON_INT = ("exception",)

_USAGE_FIELDS = ("tokens_in", "tokens_out", "cache_read", "cache_write")


def _now() -> str:
    """UTC timestamp with milliseconds, matching the AuditEvent ts pattern."""
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return stamp[:-3] + "Z"


def _check_scrub_detail(detail: dict[str, Any]) -> None:
    """A scrub event carries counts and nothing else.

    The control this enforces: the run log records how many placeholders were substituted,
    never what they replaced. An id belongs in `target`, not in the detail.
    """
    bad: list[str] = []
    for key, value in detail.items():
        if key in _SCRUB_ALLOWED_NON_INT:
            continue
        values = value.items() if isinstance(value, dict) else [(key, value)]
        for sub_key, sub_value in values:
            if isinstance(sub_value, bool) or not isinstance(sub_value, int):
                bad.append(
                    "$.detail.%s: a scrub event carries counts only, got %s"
                    % (key if sub_key == key else "%s.%s" % (key, sub_key),
                       type(sub_value).__name__)
                )
    if bad:
        raise ContractViolation("AuditEvent", sorted(set(bad)))


class Audit:
    """The run log for one run id, rooted at a store path."""

    def __init__(self, run_id: str, store_path: str | os.PathLike[str]) -> None:
        self.run_id = run_id
        self.store_path = Path(store_path)
        self.run_dir = self.store_path / "runs" / run_id
        self.log_path = self.run_dir / "run.log.jsonl"

    # ------------------------------------------------------------------ writing

    def log(
        self,
        *,
        agent: str,
        action: str,
        stage: str,
        target: str,
        model_tier: str | None = None,
        model_id: str | None = None,
        prompt_hash: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        cost_usd: float = 0.0,
        outcome: str = "ok",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stamp, validate and append one event. Returns the event that was written."""
        event: dict[str, Any] = {
            "schema_version": schema_version("AuditEvent"),
            "ts": _now(),
            "run_id": self.run_id,
            "agent": agent,
            "action": action,
            "stage": stage,
            "target": target,
            "model_tier": model_tier,
            "model_id": model_id,
            "prompt_hash": prompt_hash,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "cache_read": int(cache_read),
            "cache_write": int(cache_write),
            "cost_usd": float(cost_usd),
            "outcome": outcome,
            "detail": dict(detail or {}),
        }
        if action == "scrub":
            _check_scrub_detail(event["detail"])
        validate(event, "AuditEvent")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=False)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        return event

    def read(
        self,
        agent: str,
        target: str,
        stage: str = "store",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sugar for the read event. Reads are logged; that is the whole point of the log."""
        return self.log(agent=agent, action="read", stage=stage, target=target, detail=detail)

    @contextlib.contextmanager
    def timed(self, agent: str, action: str, stage: str, target: str) -> Iterator[dict[str, Any]]:
        """Time a block and write one event for it.

        Yields a mutable dict the body fills with any keyword argument `log` accepts. On the
        way out `detail.duration_ms` is merged in. If the body raised, the event is written
        with outcome error and `detail.exception`, then the exception is re raised.
        """
        fields: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield fields
        except BaseException as exc:
            self._write_timed(fields, agent, action, stage, target, started,
                              outcome="error", exception=type(exc).__name__)
            raise
        self._write_timed(fields, agent, action, stage, target, started)

    def _write_timed(
        self,
        fields: dict[str, Any],
        agent: str,
        action: str,
        stage: str,
        target: str,
        started: float,
        outcome: str | None = None,
        exception: str | None = None,
    ) -> dict[str, Any]:
        fields = dict(fields)
        detail = dict(fields.pop("detail", None) or {})
        detail["duration_ms"] = int(round((time.perf_counter() - started) * 1000))
        if exception is not None:
            detail["exception"] = exception
        resolved_outcome = outcome or fields.pop("outcome", "ok")
        fields.pop("outcome", None)
        return self.log(
            agent=fields.pop("agent", agent),
            action=fields.pop("action", action),
            stage=fields.pop("stage", stage),
            target=fields.pop("target", target),
            outcome=resolved_outcome,
            detail=detail,
            **fields,
        )

    # ------------------------------------------------------------------ reading

    def events(self) -> list[dict[str, Any]]:
        """Every event of this run, read back from the file so the log is the source of truth."""
        if not self.log_path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with self.log_path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ContractViolation(
                        "AuditEvent", ["line %d of %s is not JSON: %s" % (number, self.log_path, exc)]
                    ) from exc
        return out

    # ------------------------------------------------------------------ summary

    def summary(self) -> dict[str, Any]:
        """The counts, rejected_by_reason, pii_redactions_by_kind and usage RunManifest blocks.

        Derivation, stated once so nothing has to guess:

        - Any event may carry an explicit counter in `detail` under one of the manifest count
          names. Those are summed. That is the escape hatch a stage uses when only it knows
          the number, for example `sources_listed`.
        - `read` events at stage connect count one listed source each; at stage extract they
          count one source read each.
        - `withhold` events add `detail.count` to comments_withheld.
        - `scrub` events add their kind counters to pii_redactions_by_kind and their total to
          pii_redactions.
        - An event whose outcome is rejected adds `detail.count` (default 1) to
          claims_rejected and to rejected_by_reason under `detail.reason_code`.
        - `propose` events count proposals written, `approve` events with outcome ok count
          issues filed.
        - usage sums tokens and cost by stage and by tier; `calls` counts call_model events.
        """
        counts = {name: 0 for name in COUNT_FIELDS}
        rejected_by_reason = {name: 0 for name in REJECT_REASONS}
        pii_by_kind = {kind: 0 for kind in PII_KINDS}
        by_stage: dict[str, dict[str, Any]] = {}
        by_tier: dict[str, dict[str, Any]] = {}

        for event in self.events():
            detail = event.get("detail") or {}
            action = event.get("action")
            stage = event.get("stage")
            outcome = event.get("outcome")

            for name in COUNT_FIELDS:
                value = detail.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    counts[name] += value

            if action == "read" and stage == "connect":
                counts["sources_listed"] += 1
            elif action == "read" and stage == "extract":
                counts["sources_read"] += 1
            elif action == "withhold":
                counts["comments_withheld"] += _int(detail.get("count"), 0)
            elif action == "scrub":
                for kind in PII_KINDS:
                    found = detail.get(kind)
                    if found is None and isinstance(detail.get("counts"), dict):
                        found = detail["counts"].get(kind)
                    hits = _int(found, 0)
                    pii_by_kind[kind] += hits
                    counts["pii_redactions"] += hits
            elif action == "propose" and outcome == "ok":
                counts["proposals_written"] += 1
            elif action == "approve" and outcome == "ok":
                counts["issues_filed"] += 1

            if outcome == "rejected":
                rejected = _int(detail.get("count"), 1)
                counts["claims_rejected"] += rejected
                reason = detail.get("reason_code")
                if reason in rejected_by_reason:
                    rejected_by_reason[reason] += rejected

            if stage in STAGES:
                _accumulate(by_stage.setdefault(stage, _blank("stage", stage)), event)
            tier = event.get("model_tier")
            if tier in TIERS:
                _accumulate(by_tier.setdefault(tier, _blank("tier", tier)), event)

        stage_rows = [by_stage[s] for s in STAGES if s in by_stage and _nonzero(by_stage[s])]
        tier_rows = [by_tier[t] for t in TIERS if t in by_tier and _nonzero(by_tier[t])]
        total = _blank(None, None)
        for row in stage_rows:
            for field in ("calls",) + _USAGE_FIELDS:
                total[field] += row[field]
            total["cost_usd"] += row["cost_usd"]
        total["cost_usd"] = round(total["cost_usd"], 6)
        for row in stage_rows + tier_rows:
            row["cost_usd"] = round(row["cost_usd"], 6)

        return {
            "counts": counts,
            "rejected_by_reason": rejected_by_reason,
            "pii_redactions_by_kind": pii_by_kind,
            "usage": {"by_stage": stage_rows, "by_tier": tier_rows, "total": total},
        }


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _blank(key: str | None, value: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {}
    if key is not None:
        row[key] = value
    row.update({"calls": 0, "tokens_in": 0, "tokens_out": 0, "cache_read": 0,
                "cache_write": 0, "cost_usd": 0.0})
    return row


def _accumulate(row: dict[str, Any], event: dict[str, Any]) -> None:
    if event.get("action") == "call_model":
        row["calls"] += 1
    for field in _USAGE_FIELDS:
        row[field] += _int(event.get(field), 0)
    cost = event.get("cost_usd")
    row["cost_usd"] += float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else 0.0


def _nonzero(row: dict[str, Any]) -> bool:
    return bool(row["calls"] or row["cost_usd"] or any(row[f] for f in _USAGE_FIELDS))
