"""The command line. Seven verbs, six global flags, six exit codes.

    python -m digest ingest  --day 2026-09-08
    python -m digest ingest  --since-watermark
    python -m digest build   --week 2026-W37 [--stability]
    python -m digest eval
    python -m digest ask     "why does the renewal credit issue matter"
    python -m digest approve --theme THEME-0003 --yes [--repo owner/name] [--dry-run]
    python -m digest demo
    python -m digest swap    --models config/models.cheap.yaml --week 2026-W37

Global flags are accepted before or after the verb, because typing `--mode record` after
`demo` is what everybody does the first time and an argument parser that punishes it is a
small piece of hostility.

Exit codes come from `digest.errors.exit_code_for` and nowhere else: 0 ok, 2 contract
violation, 3 replay miss, 4 refused, 5 eval failure, 1 anything unexpected. The two GitHub
workflows and `make demo` branch on them.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from digest import pipeline
from digest.audit import Audit
from digest.errors import DigestError, EvalFailure, GateRefused, ReplayMiss, exit_code_for
from digest.eval import report_markdown, run_eval
from digest.gate import approve as gate_approve
from digest.pipeline import Context
from digest.swap import swap as run_swap

__all__ = ["main", "build_parser"]

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_STORE = "../bi-theme-digest-store"
_DEFAULT_MODELS = "config/models.yaml"
_DEFAULT_MOCK = "data/mock"

_GLOBALS = ("mode", "store", "models", "responses_dir", "mock_dir", "log_level")


def _add_globals(parser: argparse.ArgumentParser, *, suppress: bool,
                 with_models: bool = True) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument("--mode", choices=("replay", "live", "record"),
                        default=(argparse.SUPPRESS if suppress else "replay"),
                        help="router mode; replay is the default so the demo is free")
    parser.add_argument("--store", default=(argparse.SUPPRESS if suppress else _DEFAULT_STORE),
                        help="the context store repository")
    if with_models:
        parser.add_argument("--models",
                            default=(argparse.SUPPRESS if suppress else _DEFAULT_MODELS),
                            help="the tier map, the only file that names a model")
    parser.add_argument("--responses-dir", default=default,
                        help="where recordings are read and written")
    parser.add_argument("--mock-dir", default=(argparse.SUPPRESS if suppress else _DEFAULT_MOCK),
                        help="passed to the MCP servers as DIGEST_MOCK_DIR")
    parser.add_argument("--log-level", default=(argparse.SUPPRESS if suppress else "INFO"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digest", description=__doc__.splitlines()[0])
    _add_globals(parser, suppress=False)
    verbs = parser.add_subparsers(dest="verb", required=True)

    ingest = verbs.add_parser("ingest", help="ingest one day, or every day after the watermark")
    ingest.add_argument("--day", help="a single calendar day, YYYY-MM-DD")
    ingest.add_argument("--since-watermark", action="store_true",
                        help="every corpus day after sources/_INDEX.md's last_ingest_day")
    _add_globals(ingest, suppress=True)

    build = verbs.add_parser("build", help="build one week's digest")
    build.add_argument("--week", required=True, help="a week label, for example 2026-W37")
    build.add_argument("--stability", action="store_true",
                       help="run the editor a second time into a scratch copy and report overlap")
    _add_globals(build, suppress=True)

    evaluate = verbs.add_parser("eval", help="run evals/golden_set.yaml against the store")
    evaluate.add_argument("--week", action="append", dest="weeks",
                          help="restrict to one week; repeatable")
    _add_globals(evaluate, suppress=True)

    ask = verbs.add_parser("ask", help="ask the analyst one question about the theme store")
    ask.add_argument("question")
    _add_globals(ask, suppress=True)

    approve = verbs.add_parser("approve", help="file the GitHub issue for one proposed theme")
    approve.add_argument("--theme", required=True)
    approve.add_argument("--yes", action="store_true", help="the human gate; nothing files without it")
    approve.add_argument("--repo", default=None, help="owner/name, or set DIGEST_ISSUES_REPO")
    approve.add_argument("--dry-run", action="store_true",
                         help="print the issue and file nothing; implies --yes")
    _add_globals(approve, suppress=True)

    demo = verbs.add_parser("demo", help="every ingest day and every week, in order")
    _add_globals(demo, suppress=True)

    swap = verbs.add_parser("swap", help="rerun one week with an alternate tier map")
    swap.add_argument("--models", dest="alt_models", required=True,
                      help="the ALTERNATE tier map to compare against the reference")
    swap.add_argument("--week", required=True)
    swap.add_argument("--reference-models", default=None,
                      help="the reference tier map; defaults to the global --models")
    _add_globals(swap, suppress=True, with_models=False)

    return parser


def _context(args: argparse.Namespace) -> Context:
    store = Path(args.store)
    if not store.is_absolute():
        store = (_REPO / store).resolve()
    models = Path(args.models)
    if not models.is_absolute():
        models = (_REPO / models).resolve()
    mock = Path(args.mock_dir)
    if not mock.is_absolute():
        mock = (_REPO / mock).resolve()
    return Context(store_path=store, models_path=models, mode=args.mode,
                   responses_dir=args.responses_dir, mock_dir=mock)


def _days_since_watermark(context: Context) -> list[str]:
    _run, watermark = context.store().read_watermark()
    if watermark is None:
        return list(pipeline.INGEST_DAYS)
    return [day for day in pipeline.INGEST_DAYS if day > watermark.isoformat()]


def _run(args: argparse.Namespace) -> int:
    context = _context(args)

    if args.verb == "ingest":
        if bool(args.day) == bool(args.since_watermark):
            raise DigestError("ingest takes exactly one of --day and --since-watermark")
        days = [args.day] if args.day else _days_since_watermark(context)
        if not days:
            context.say("nothing to ingest: the watermark is already at the end of the corpus")
        for day in days:
            pipeline.ingest_day(day, context)
        return 0

    if args.verb == "build":
        pipeline.build_week(args.week, context, stability=args.stability)
        return 0

    if args.verb == "demo":
        pipeline.demo(context)
        return 0

    if args.verb == "eval":
        result = run_eval(context.store(), weeks=args.weeks, context=context,
                          mock_dir=context.mock_dir)
        sys.stdout.write(report_markdown(result))
        if result["failed"]:
            raise EvalFailure(r["id"] for r in result["results"] if not r["passed"])
        return 0

    if args.verb == "ask":
        pipeline.ask(args.question, context)
        return 0

    if args.verb == "approve":
        store = context.store()
        audit = Audit(pipeline.APPROVE_RUN_ID, store.path)
        store.attach_audit(audit)
        # A dry run files nothing, so it does not need the human gate. A real one does, and
        # --yes is the only thing that supplies it.
        url = gate_approve(args.theme, yes=args.yes or args.dry_run, repo=args.repo,
                           store=store, dry_run=args.dry_run, audit=audit)
        if url:
            context.say(url)
        return 0

    if args.verb == "swap":
        reference = args.reference_models or args.models
        reference_path = Path(reference)
        if not reference_path.is_absolute():
            reference_path = (_REPO / reference_path).resolve()
        alternate = Path(args.alt_models)
        if not alternate.is_absolute():
            alternate = (_REPO / alternate).resolve()
        context = context.with_overrides(models_path=reference_path)
        run_swap(args.week, context, alternate, mode=args.mode)
        return 0

    raise DigestError("unknown verb %r" % args.verb)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    # A global given after the verb lands on the subparser namespace; anything not given
    # there keeps the top level value, which is how both positions work.
    for name in _GLOBALS:
        if not hasattr(args, name):
            setattr(args, name, None)
    if getattr(args, "models", None) is None:
        args.models = _DEFAULT_MODELS
    logging.basicConfig(level=getattr(logging, str(args.log_level or "INFO").upper(), logging.INFO),
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        return _run(args)
    except ReplayMiss as exc:
        sys.stderr.write("replay miss: %s\n" % exc)
        return exit_code_for(exc)
    except GateRefused as exc:
        sys.stderr.write("refused: %s\n" % exc)
        return exit_code_for(exc)
    except EvalFailure as exc:
        sys.stderr.write("eval failure: %s\n" % exc)
        return exit_code_for(exc)
    except DigestError as exc:
        sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc))
        return exit_code_for(exc)
    except BaseException as exc:  # noqa: BLE001 - the top level is where everything lands
        logging.getLogger("digest").exception("unexpected failure")
        sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc))
        return exit_code_for(exc)


if __name__ == "__main__":
    raise SystemExit(main())
