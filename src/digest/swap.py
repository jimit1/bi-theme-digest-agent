"""Swap the tier map and print what it cost you.

The routing argument in this prototype is that the model is a configuration value, not an
architectural commitment. That claim is only worth making if it is checkable, so this
module makes it checkable in one command: rerun one week's build with a different tier map
and print three lines of comparison.

How the comparison is made fair. Both runs start from the SAME store state, the commit the
real build started from, cloned into a scratch directory. The reference side is the recorded
reference run replayed, which costs nothing and reports the cost that was actually paid. The
alternate side runs against the alternate tier map, recording into its own directory inside
the real store so the swap can be replayed later without paying for it twice. Neither side
can touch the real store's themes, because neither side is pointed at it.
"""
from __future__ import annotations

import pathlib
import tempfile
from typing import Any

from digest.agents.editor.editor import run_id_for_week
from digest.eval import run_eval
from digest.pipeline import (Context, _themes_of, assignment_pairs, co_assignment, jaccard,
                             rerun_week, top_three)

__all__ = ["swap", "report_lines", "SWAP_RESPONSES"]

# Inside the real store, so the recordings are committed and the swap replays for free.
SWAP_RESPONSES = "responses-swap"


def swap(week: str, context: Context, models_path: str | pathlib.Path,
         mode: str | None = None) -> dict[str, Any]:
    """Rerun `week` with an alternate tier map and compare it to the reference run.

    Returns the comparison. `mode` is the mode for the ALTERNATE side only: the reference
    side is always replayed from its own committed recordings, because paying twice for a
    number you already have is not a measurement, it is a bill.
    """
    run_id = run_id_for_week(week)
    alternate_mode = mode or context.mode
    reference_responses = context.store_path / "runs" / run_id / "responses"
    alternate_responses = context.store_path / "runs" / run_id / SWAP_RESPONSES
    alternate_responses.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="digest-swap-") as tmp:
        root = pathlib.Path(tmp)
        reference_store, reference_manifest = rerun_week(
            week, context, root / "reference", models_path=context.models_path,
            mode="replay", responses_dir=reference_responses)
        reference_eval = run_eval(reference_store, weeks=[week], context=None)
        reference_themes = _themes_of(reference_store)

        alternate_store, alternate_manifest = rerun_week(
            week, context, root / "alternate", models_path=pathlib.Path(models_path),
            mode=alternate_mode, responses_dir=alternate_responses)
        alternate_eval = run_eval(alternate_store, weeks=[week], context=None)
        alternate_themes = _themes_of(alternate_store)

    context.activate()
    reference_pairs = assignment_pairs(reference_themes)
    alternate_pairs = assignment_pairs(alternate_themes)
    # Both sides allocate theme ids from the same empty index, so the ids they hand out are
    # arbitrary labels. The headline overlap is therefore the label independent one: did the
    # cheaper tier map put the same claims together. The labelled number is kept beside it.
    claim_ids = {claim_id for claim_id, _theme in reference_pairs | alternate_pairs}
    comparison = {
        "week": week,
        "run_id": run_id,
        "reference_models": str(context.models_path),
        "alternate_models": str(models_path),
        "mode": alternate_mode,
        "reference_cost_usd": reference_manifest["usage"]["total"]["cost_usd"],
        "alternate_cost_usd": alternate_manifest["usage"]["total"]["cost_usd"],
        "reference_eval": [reference_eval["passed"], reference_eval["total"]],
        "alternate_eval": [alternate_eval["passed"], alternate_eval["total"]],
        "jaccard": round(jaccard(co_assignment(reference_themes, claim_ids),
                                 co_assignment(alternate_themes, claim_ids)), 6),
        "labelled_jaccard": round(jaccard(reference_pairs, alternate_pairs), 6),
        "reference_themes": len(reference_themes),
        "alternate_themes": len(alternate_themes),
        "top3_stable": top_three(alternate_themes) == top_three(reference_themes),
        "reference_top3": top_three(reference_themes),
        "alternate_top3": top_three(alternate_themes),
        "responses_dir": str(alternate_responses),
    }
    for line in report_lines(comparison):
        context.say(line)
    # The alternate recordings live in the real store, so commit them: that is what makes
    # the comparison replayable by a reader who never pays for it.
    context.store().commit(
        "run %s: swap %s onto %s, jaccard %.3f"
        % (run_id, week, pathlib.Path(models_path).name, comparison["jaccard"]), run_id)
    return comparison


def report_lines(comparison: dict[str, Any]) -> list[str]:
    """The three lines. Cost, eval pass rate, overlap. Nothing else fits on a slide."""
    reference = comparison["reference_cost_usd"]
    alternate = comparison["alternate_cost_usd"]
    share = (alternate / reference * 100.0) if reference else 0.0
    return [
        "cost:    reference $%.4f, alternate $%.4f (%.1f percent of reference)"
        % (reference, alternate, share),
        "eval:    reference %d of %d assertions, alternate %d of %d"
        % (*comparison["reference_eval"], *comparison["alternate_eval"]),
        "overlap: claim co-assignment jaccard %.3f (with theme ids %.3f), %d themes against "
        "%d, top three %s (%s vs %s)"
        % (comparison["jaccard"], comparison["labelled_jaccard"],
           comparison["alternate_themes"], comparison["reference_themes"],
           "stable" if comparison["top3_stable"] else "CHANGED",
           comparison["reference_top3"], comparison["alternate_top3"]),
    ]
