"""The golden set, run mechanically against the store.

`evals/golden_set.yaml` is the acceptance test for the whole prototype: five claims that
must appear with the exact place they came from, two sentences that must never appear, four
planted PII values that must never appear, and seven structural assertions. Nothing here
asks a model anything. Every assertion is a join, a substring test or a comparison, which is
the only way an eval is worth running twice.

The output is markdown on stdout, one line per assertion, and a non zero exit when one
fails. `digest.errors.EvalFailure` carries the failed ids, so a red CI job names them
without anybody opening a log.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Iterable

import yaml

from digest.errors import ContractViolation
from digest.store import Store
from digest.verify import resolve_citation

__all__ = ["Assertion", "golden_path", "load_golden", "run_eval", "report_markdown"]

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SKIP_DIRS = (".git",)


class Assertion(dict):
    """One checked assertion: id, kind, description, passed, detail."""


def _result(ident: str, kind: str, description: str, passed: bool, detail: str = "") -> Assertion:
    return Assertion(id=ident, kind=kind, description=description, passed=bool(passed),
                     detail=detail)


def golden_path() -> pathlib.Path:
    return _REPO / "evals" / "golden_set.yaml"


def load_golden(path: str | pathlib.Path | None = None) -> dict[str, Any]:
    text = pathlib.Path(path or golden_path()).read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ContractViolation("GoldenSet", ["$: the golden set is not a mapping"])
    return document


# --------------------------------------------------------------------------- store reading


def _themes(store: Store) -> list[dict[str, Any]]:
    return [store.read_theme(line["theme_id"])[0] for line in store.read_theme_index()]


def _claims(store: Store) -> dict[str, dict[str, Any]]:
    return {claim["claim_id"]: claim for claim in store.read_claims()}


def _source_id_of(claim: dict[str, Any]) -> str:
    ref = claim["source_ref"]
    return ref["call_id"] if claim["source"] == "gong" else ref["case_id"]


def _theme_of_claim(themes: Iterable[dict[str, Any]], claim_id: str) -> str | None:
    for theme in themes:
        if claim_id in (theme.get("evidence") or []):
            return theme["theme_id"]
    return None


def _store_files(store: Store) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for path in store.path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(store.path).parts):
            continue
        out.append(path)
    return out


def _grep_store(store: Store, needle: str, outputs_only: bool = False) -> list[str]:
    """Every file in the store repository containing `needle`.

    `outputs_only` drops the two places that hold what the agent was SHOWN rather than what
    it produced: `sources/` is the scrubbed source document, which file_formats.md section 7
    requires to be the document exactly as the reader saw it, and `runs/*/responses*/` holds
    recorded requests, whose prompt text is that same document. The golden set's two
    must_not_appear entries say the sentences must never reach an output, "not a claim, not
    the digest, not a proposal, not the audit log": a sentence a Momentive Software employee
    actually said is in the transcript by construction, and the control being demonstrated is
    that it never becomes a claim. The PII values are checked against the whole repository,
    because those must not exist anywhere at all.
    """
    hits: list[str] = []
    for path in _store_files(store):
        relative = path.relative_to(store.path)
        parts = relative.parts
        if outputs_only and (parts[0] == "sources"
                             or (parts[0] == "runs" and len(parts) > 2
                                 and parts[2].startswith("responses"))):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle in text:
            hits.append(str(relative))
    return hits


def _locate(entry: dict[str, Any], claims: dict[str, dict[str, Any]]
            ) -> tuple[dict[str, Any] | None, bool]:
    """The claim a golden set must_appear entry names, and whether the span matched exactly.

    Two ways to name it, in this order. The planted substring, which is what the entry
    asserts on. Failing that, the entry's own turn locator: `speaker_id` for a Gong call,
    `comment_id` for a Salesforce case. The second exists because the reader prompt says
    "one claim per distinct point", so when a fixture states the planted point twice the
    reader is required to quote it once and may pick either statement. The structural
    assertions are about which THEME the trap landed on, so they use the locator; the
    must_appear assertion itself still insists on the planted span.
    """
    from_source = [c for c in claims.values() if _source_id_of(c) == str(entry["source_id"])]
    needle = entry.get("expected_verbatim_substring") or ""
    exact = [c for c in from_source if needle and needle in c["verbatim"]]
    if exact:
        return exact[0], True
    if entry.get("source") == "gong" and entry.get("speaker_id"):
        same_speaker = [c for c in from_source
                        if c["source_ref"].get("speaker_id") == str(entry["speaker_id"])]
        if same_speaker:
            return same_speaker[0], False
    if entry.get("comment_id"):
        same_comment = [c for c in from_source
                        if c["source_ref"].get("comment_id") == str(entry["comment_id"])]
        if same_comment:
            return same_comment[0], False
    return None, False


def _digest_text(store: Store, week: str) -> str:
    path = store.path / "digests" / ("%s.md" % week)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _corpus_source_ids(theme_key: str, mock_dir: pathlib.Path | None = None) -> set[str]:
    """Which mock documents carry a planted theme key, read off the corpus index."""
    index_path = (mock_dir or (_REPO / "data" / "mock")) / "index.json"
    document = json.loads(index_path.read_text(encoding="utf-8"))
    return {entry["id"] for entry in document["entries"] if entry.get("theme_key") == theme_key}


# --------------------------------------------------------------------------- the checks


def _check_must_appear(entry: dict[str, Any], store: Store, themes: list[dict[str, Any]],
                       claims: dict[str, dict[str, Any]], week: str) -> Assertion:
    ident = entry["id"]
    needle = entry["expected_verbatim_substring"]
    claim, exact = _locate(entry, claims)
    if claim is None:
        return _result(ident, "must_appear", "claim from %s is in the store" % entry["source_id"],
                       False, "no stored claim from %s quotes %r or cites its turn"
                       % (entry["source_id"], needle[:60]))
    problems: list[str] = []
    if not exact:
        problems.append(
            "the reader quoted a different span from speaker %s (turn at %s ms): %r, "
            "not the planted %r" % (claim["source_ref"].get("speaker_id"),
                                    claim["source_ref"].get("start_ms"),
                                    claim["verbatim"][:70], needle[:50]))
    if claim["account_id"] != entry["expected_account_id"]:
        problems.append("account_id %s, expected %s" % (claim["account_id"],
                                                        entry["expected_account_id"]))
    if claim["account_type"] != entry["expected_account_type"]:
        problems.append("account_type %s, expected %s" % (claim["account_type"],
                                                          entry["expected_account_type"]))
    if claim["speaker_side"] != entry["expected_speaker_side"]:
        problems.append("speaker_side %s, expected %s" % (claim["speaker_side"],
                                                          entry["expected_speaker_side"]))
    theme_id = _theme_of_claim(themes, claim["claim_id"])
    if theme_id is None:
        problems.append("claim %s is attached to no theme" % claim["claim_id"])
    if claim["verbatim"] not in _digest_text(store, week):
        problems.append("the verbatim is not in digests/%s.md" % week)
    return _result(ident, "must_appear",
                   "claim from %s appears, cited, on a theme and in the digest" % entry["source_id"],
                   not problems, "; ".join(problems) or "theme %s, claim %s"
                   % (theme_id, claim["claim_id"]))


def _check_must_not_appear(entry: dict[str, Any], store: Store) -> Assertion:
    hits = _grep_store(store, entry["forbidden_substring"], outputs_only=True)
    shown = _grep_store(store, entry["forbidden_substring"])
    note = ("absent from every output; it is in %d file(s) holding what the reader was "
            "shown, which is where a transcript sentence belongs" % len(shown)) if shown \
        else "absent from every file in the store"
    return _result(entry["id"], "must_not_appear", entry["reason"], not hits,
                   ("found in %s" % ", ".join(hits[:5])) if hits else note)


def _check_pii(value: str, kind: str, store: Store) -> Assertion:
    hits = _grep_store(store, value)
    return _result("PII-%s" % kind, "pii",
                   "the planted %s never reaches the store" % kind, not hits,
                   ("found in %s" % ", ".join(hits[:5])) if hits else "absent")


def _s1(store: Store, themes: list[dict[str, Any]],
        claims: dict[str, dict[str, Any]]) -> Assertion:
    checked = 0
    problems: list[str] = []
    for theme in themes:
        for claim_id in theme.get("evidence") or []:
            claim = claims.get(claim_id)
            if claim is None:
                problems.append("%s cites claim %s, which is not in the store"
                                % (theme["theme_id"], claim_id))
                continue
            try:
                span = resolve_citation(claim, store.read_source_document(_source_id_of(claim)))
            except Exception as exc:  # noqa: BLE001 - any failure is an unresolved citation
                problems.append("%s: %s" % (claim_id, exc))
                continue
            checked += 1
            if claim["verbatim"] not in span:
                problems.append("%s: verbatim is not a substring of the cited turn" % claim_id)
    return _result("S1", "structural",
                   "every claim in the digest carries a citation and every citation resolves",
                   not problems, "; ".join(problems[:5]) or "%d citations resolved" % checked)


def _trap_themes(golden: dict[str, Any], trap: str, themes: list[dict[str, Any]],
                 claims: dict[str, dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Which themes the planted claims of one trap landed on, and which sources were found.

    Only the PLANTED claim of each trap document counts. A generated call also carries
    ordinary conversation, and a reader that extracts a second, unrelated claim from the
    same call has not failed the reconciliation test; it has read the call.
    """
    theme_ids: set[str] = set()
    found: set[str] = set()
    for entry in golden.get("must_appear", []):
        if entry.get("trap") != trap:
            continue
        claim, _exact = _locate(entry, claims)
        if claim is None:
            continue
        found.add(str(entry["source_id"]))
        theme_id = _theme_of_claim(themes, claim["claim_id"])
        if theme_id:
            theme_ids.add(theme_id)
    return theme_ids, found


def _s2(check: dict[str, Any], golden: dict[str, Any], themes: list[dict[str, Any]],
        claims: dict[str, dict[str, Any]]) -> Assertion:
    wanted = {str(s) for s in check["source_ids"]}
    theme_ids, found_sources = _trap_themes(golden, "T1", themes, claims)
    passed = len(theme_ids) == 1 and found_sources == wanted
    return _result("S2", "structural",
                   "the two differently worded T1 claims sit on exactly one theme", passed,
                   "themes %s from sources %s" % (sorted(theme_ids), sorted(found_sources)))


def _s3(check: dict[str, Any], golden: dict[str, Any], themes: list[dict[str, Any]],
        claims: dict[str, dict[str, Any]]) -> Assertion:
    theme_ids, _found = _trap_themes(golden, "T2", themes, claims)
    if len(theme_ids) != 1:
        return _result("S3", "structural", "the T2 theme carries both product names",
                       False, "the T2 claims are on themes %s" % sorted(theme_ids))
    theme = next(t for t in themes if t["theme_id"] in theme_ids)
    blob = " ; ".join(theme.get("aliases") or []).lower()
    missing = [name for name in check["names"] if name.lower() not in blob]
    return _result("S3", "structural",
                   "the T2 theme carries both product names in its aliases", not missing,
                   ("%s missing from %s aliases %s" % (missing, theme["theme_id"],
                                                       theme.get("aliases")))
                   if missing else "%s aliases: %s" % (theme["theme_id"], theme.get("aliases")))


def _s4(check: dict[str, Any], store: Store, themes: list[dict[str, Any]],
        claims: dict[str, dict[str, Any]], week: str) -> Assertion:
    source_id = str(check["source_id"])
    prospect_claims = [c for c in claims.values() if _source_id_of(c) == source_id]
    if not prospect_claims:
        return _result("S4", "structural", "the prospect theme exists and ranks below customers",
                       False, "no claim from %s is in the store" % source_id)
    theme_id = _theme_of_claim(themes, prospect_claims[0]["claim_id"])
    theme = next((t for t in themes if t["theme_id"] == theme_id), None)
    if theme is None:
        return _result("S4", "structural", "the prospect theme exists and ranks below customers",
                       False, "the T3 claim is attached to no theme")
    problems: list[str] = []
    if theme["score_inputs"]["distinct_customers"] != 0:
        problems.append("%s is not prospect only" % theme_id)
    if check["account_id"] not in (theme.get("accounts") or []):
        problems.append("%s is not on %s" % (check["account_id"], theme_id))
    for other in themes:
        if other["theme_id"] == theme_id:
            continue
        if other["score_inputs"]["distinct_customers"] > 0 \
                and other["score_inputs"]["claim_count"] == theme["score_inputs"]["claim_count"] \
                and other["score"] <= theme["score"]:
            problems.append("%s (customer backed, same claim count) scores %d, not above %d"
                            % (other["theme_id"], other["score"], theme["score"]))
    if theme["title"] not in _digest_text(store, week):
        problems.append("%s is not in digests/%s.md" % (theme_id, week))
    return _result("S4", "structural",
                   "the prospect theme appears but ranks below every customer backed theme "
                   "of equal claim count", not problems,
                   "; ".join(problems[:4]) or "%s scores %d on %d prospect claims"
                   % (theme_id, theme["score"], theme["score_inputs"]["claim_count"]))


def _s6(check: dict[str, Any], store: Store, context: Any) -> Assertion:
    """A second build over the same input produces the same theme ids.

    Run for real rather than asserted: the store is cloned at the commit the build started
    from and the build is run again in replay mode against the committed recordings, which
    costs nothing and is a genuine second build.
    """
    import tempfile

    from digest.pipeline import rerun_week

    run_id = check["build_run_id"]
    week = check["week"]
    expected = {t["theme_id"]: t["title"] for t in _themes(store)
                if t.get("created_run") == run_id}
    if not expected:
        return _result("S6", "structural", "a rerun produces the same theme ids", False,
                       "no theme was created by run %s" % run_id)
    if context is None:
        return _result("S6", "structural", "a rerun produces the same theme ids", False,
                       "no pipeline context was supplied to rerun the build")
    try:
        with tempfile.TemporaryDirectory(prefix="digest-eval-") as tmp:
            scratch, _manifest = rerun_week(
                week, context, pathlib.Path(tmp) / "store", mode="replay",
                responses_dir=store.path / "runs" / run_id / "responses")
            second = {t["theme_id"]: t["title"] for t in _themes(scratch)
                      if t.get("created_run") == run_id}
    except Exception as exc:  # noqa: BLE001 - a rerun that cannot run is a failed assertion
        return _result("S6", "structural", "a rerun produces the same theme ids", False,
                       "the rerun failed: %s: %s" % (type(exc).__name__, exc))
    finally:
        context.activate()
    return _result("S6", "structural",
                   "a second build over the same input produces the same theme ids",
                   second == expected,
                   "rerun produced %s, the store has %s" % (sorted(second), sorted(expected))
                   if second != expected else "%d themes, identical ids" % len(expected))


def _s7(check: dict[str, Any], store: Store, themes: list[dict[str, Any]],
        claims: dict[str, dict[str, Any]], mock_dir: pathlib.Path | None) -> Assertion:
    sources = _corpus_source_ids(check["theme_key"], mock_dir)
    theme_ids = {
        _theme_of_claim(themes, c["claim_id"])
        for c in claims.values() if _source_id_of(c) in sources
    } - {None}
    if not theme_ids:
        return _result("S7", "structural", "the stale flag fires on the W39 digest", False,
                       "no theme carries a %s claim" % check["theme_key"])
    flagged = [t for t in themes if t["theme_id"] in theme_ids and t["stale"]]
    quiet = [t for t in themes if t["theme_id"] in theme_ids and t["status"] == "quiet"]
    text = _digest_text(store, check["week"])
    problems: list[str] = []
    if not flagged:
        problems.append("none of %s is stale" % sorted(theme_ids))
    if not quiet:
        problems.append("none of %s is quiet" % sorted(theme_ids))
    if flagged and flagged[0]["title"] not in text:
        problems.append("%s is not in digests/%s.md" % (flagged[0]["theme_id"], check["week"]))
    if flagged and "stale" not in text.lower():
        problems.append("digests/%s.md does not say stale" % check["week"])
    return _result("S7", "structural",
                   "the stale flag fires on the one theme that received nothing for two weeks",
                   not problems,
                   "; ".join(problems[:4]) or "%s: %s"
                   % (flagged[0]["theme_id"], flagged[0]["stale_reason"]))


# --------------------------------------------------------------------------- the runner


def run_eval(store: Store, golden: dict[str, Any] | None = None, *,
             weeks: Iterable[str] | None = None, context: Any = None,
             mock_dir: pathlib.Path | None = None) -> dict[str, Any]:
    """Run every assertion in the golden set against `store`.

    `weeks` restricts the run to assertions about those weeks, which is what the model swap
    comparison uses: a scratch store that only has week 37 cannot be asked about week 39.
    """
    golden = golden or load_golden()
    week = golden["week"]
    only = set(weeks) if weeks is not None else None
    themes = _themes(store)
    claims = _claims(store)
    results: list[Assertion] = []

    if only is None or week in only:
        for entry in golden.get("must_appear", []):
            results.append(_check_must_appear(entry, store, themes, claims, week))
    for entry in golden.get("must_not_appear", []):
        results.append(_check_must_not_appear(entry, store))
    for entry in golden.get("pii_must_not_appear", []):
        results.append(_check_pii(entry["value"], entry["kind"], store))

    for item in golden.get("structural", []):
        check = item["check"]
        name = check["name"]
        target_week = check.get("week", week)
        if only is not None and target_week not in only:
            continue
        if name == "every_claim_cited_and_resolves":
            results.append(_s1(store, themes, claims))
        elif name == "t1_single_theme":
            results.append(_s2(check, golden, themes, claims))
        elif name == "t2_aliases_both_names":
            results.append(_s3(check, golden, themes, claims))
        elif name == "t3_prospect_ranks_below_customers":
            results.append(_s4(check, store, themes, claims, week))
        elif name == "no_pii_in_store":
            hits = {v: _grep_store(store, v) for v in check["values"]}
            bad = {v: f for v, f in hits.items() if f}
            results.append(_result("S5", "structural", item["description"], not bad,
                                   "leaked: %s" % sorted(bad) if bad
                                   else "%d values, none present" % len(hits)))
        elif name == "rerun_same_theme_ids":
            # This one runs a whole build again, so it needs a pipeline context. A caller
            # that deliberately passes none (the model swap, comparing two scratch stores)
            # drops the assertion rather than failing it: rerun determinism is a property
            # of the pipeline, and it is not what a tier map comparison is measuring.
            if context is not None:
                results.append(_s6(check, store, context))
        elif name == "stale_flag_fires_w39":
            results.append(_s7(check, store, themes, claims, mock_dir))
        else:
            results.append(_result(item["id"], "structural", item["description"], False,
                                   "no checker implements %s" % name))

    passed = sum(1 for r in results if r["passed"])
    return {
        "results": results,
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
        "pass_rate": (passed / len(results)) if results else 1.0,
        "stability": _stability_rows(store),
    }


def _stability_rows(store: Store) -> list[dict[str, Any]]:
    """Whatever stability numbers the build runs recorded. Reported, not asserted."""
    rows: list[dict[str, Any]] = []
    runs = store.path / "runs"
    for manifest_path in sorted(runs.glob("*/manifest.json")) if runs.is_dir() else []:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("run_type") == "build" and manifest.get("stability", {}).get("computed"):
            rows.append({"run_id": manifest["run_id"], "week": manifest.get("week"),
                         **manifest["stability"]})
    return rows


def report_markdown(result: dict[str, Any]) -> str:
    """The eval report. One line per assertion, so a diff of two runs is readable."""
    lines = ["# Golden set results", ""]
    lines.append("%d of %d assertions passed." % (result["passed"], result["total"]))
    lines.append("")
    lines.append("| id | kind | result | detail |")
    lines.append("| --- | --- | --- | --- |")
    for row in result["results"]:
        detail = str(row["detail"]).replace("|", "/").replace("\n", " ")[:180]
        lines.append("| %s | %s | %s | %s |"
                     % (row["id"], row["kind"], "pass" if row["passed"] else "FAIL", detail))
    lines.append("")
    lines.append("## Stability")
    lines.append("")
    if not result["stability"]:
        lines.append("No build run computed a stability number.")
    else:
        for row in result["stability"]:
            lines.append("- %s %s: jaccard %.3f, top three stable %s"
                         % (row["week"], row["run_id"], row["jaccard"], row["top3_stable"]))
    lines.append("")
    if result["failed"]:
        lines.append("Failed: %s" % ", ".join(r["id"] for r in result["results"]
                                              if not r["passed"]))
    else:
        lines.append("Every assertion passed.")
    return "\n".join(lines) + "\n"
