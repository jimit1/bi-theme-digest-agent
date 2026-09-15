"""Builds the tiny B14 fixture store: two themes, two claims, nothing else.

Shared by the pytest suite (which replays three recorded questions against it) and by
`record_live.py` (which made the three live calls this task was allowed, once, against
exactly this store). Both import `build_store` and the three `QUESTIONS` so the prompt text
a replay expects is byte for byte the prompt text the live call actually saw; the router's
replay key is a hash of that text, so the two paths cannot be allowed to drift apart.

Fictional organisations only, per build/COMMON_RULES.md rule 4. Neither account below
resembles a real Momentive Software customer.

Run it on its own to see the store it produces:

    .venv/bin/python tests/fixtures/b14/build_fixture_store.py /tmp/b14-store
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from digest.store import Store, render_theme_body  # noqa: E402

RUN_ID = "2026-09-14T07:00Z"
INGEST_RUN = "2026-09-08T06:00Z"

CLAIM_RENEWAL = {
    "schema_version": "1.0.0",
    "claim_id": "e7e3c117f5c5",
    "run_id": INGEST_RUN,
    "source": "gong",
    "source_ref": {
        "call_id": "7782934451002",
        "speaker_id": "4521",
        "speaker_name": "Dana Ruiz",
        "affiliation": "External",
        "start_ms": 418000,
        "end_ms": 437000,
    },
    "account_id": "ACC-0001",
    "account_name": "Great Lakes Museum Alliance",
    "account_type": "customer",
    "speaker_side": "client",
    "verbatim": "Our renewal invoice came through with the full annual amount and there is "
                "no line anywhere showing the dues we already paid in March.",
    "paraphrase": "Renewal invoices do not show the dues already paid earlier in the year.",
    "topic": "renewal invoice credit",
    "product_area": "membership",
    "claim_type": "support_issue",
    "importance": "high",
    "importance_reason": "Finance has to correct every renewal invoice by hand before it goes out.",
    "captured_at": "2026-09-08T06:04:11.512Z",
    "prompt_hash": "80ab0b6e75c1789d",
    "model_tier": "extraction",
}

THEME_RENEWAL = {
    "schema_version": "1.0.0",
    "theme_id": "THEME-0003",
    "title": "Renewal invoices do not show prior dues credit",
    "aliases": ["dues proration", "credit on renewal", "invoice credit line"],
    "product_area": "membership",
    "status": "open",
    "owner": "ai-operations",
    "source": "synthesized",
    "last_verified": "2026-09-14",
    "run_id": RUN_ID,
    "created_run": RUN_ID,
    "last_updated_run": RUN_ID,
    "accounts": ["ACC-0001"],
    "evidence": ["e7e3c117f5c5"],
    "score": 61,
    "score_inputs": {
        "distinct_customers": 1, "distinct_prospects": 0, "arr_sum": 240000,
        "open_cases": 1, "recency_days": 6, "claim_count": 1, "high_importance_count": 1,
    },
    "rationale": "One customer reports that renewal invoices carry the full annual amount "
                 "with no line for dues already paid, and finance corrects it by hand every "
                 "time it happens.",
    "stale": False,
    "stale_reason": None,
    "last_evidence_at": "2026-09-08T06:04:11.512Z",
    "proposal_id": None,
    "filed_issue_url": None,
}

CLAIM_IMPORT = {
    "schema_version": "1.0.0",
    "claim_id": "b30a2f7119ad",
    "run_id": INGEST_RUN,
    "source": "gong",
    "source_ref": {
        "call_id": "7782934451099",
        "speaker_id": "5501",
        "speaker_name": "Priya Nandan",
        "affiliation": "External",
        "start_ms": 122000,
        "end_ms": 141000,
    },
    "account_id": "ACC-0002",
    "account_name": "Foothill Youth Symphony",
    "account_type": "customer",
    "speaker_side": "client",
    "verbatim": "Every time we try to import our fall registration list the upload just "
                "times out once we pass about ten thousand rows.",
    "paraphrase": "Bulk registration imports time out above ten thousand rows.",
    "topic": "bulk import timeout",
    "product_area": "events",
    "claim_type": "support_issue",
    "importance": "high",
    "importance_reason": "The fall registration deadline is missed while support reruns "
                          "the import by hand in smaller batches.",
    "captured_at": "2026-09-08T06:10:22.000Z",
    "prompt_hash": "d88ece85614936b1",
    "model_tier": "extraction",
}

THEME_IMPORT = {
    "schema_version": "1.0.0",
    "theme_id": "THEME-0007",
    "title": "Bulk registration imports time out above ten thousand rows",
    "aliases": ["import timeout", "large list upload failure"],
    "product_area": "events",
    "status": "open",
    "owner": "ai-operations",
    "source": "synthesized",
    "last_verified": "2026-09-14",
    "run_id": RUN_ID,
    "created_run": RUN_ID,
    "last_updated_run": RUN_ID,
    "accounts": ["ACC-0002"],
    "evidence": ["b30a2f7119ad"],
    "score": 58,
    "score_inputs": {
        "distinct_customers": 1, "distinct_prospects": 0, "arr_sum": 180000,
        "open_cases": 1, "recency_days": 6, "claim_count": 1, "high_importance_count": 1,
    },
    "rationale": "One customer's fall registration import repeatedly times out once the "
                 "list passes ten thousand rows, so support splits the file and reruns it "
                 "by hand.",
    "stale": False,
    "stale_reason": None,
    "last_evidence_at": "2026-09-08T06:10:22.000Z",
    "proposal_id": None,
    "filed_issue_url": None,
}

# The three questions this task was allowed to spend a live call on. Reused verbatim by the
# replaying tests, because the replay key is a hash of the exact question text.
QUESTIONS = {
    "supported": "why does the renewal credit issue matter",
    "unsupported": "what have customers told us about a mobile app",
    "two_theme": "why are customers upset about renewal invoices and about the "
                 "registration import timing out",
}


def build_store(path: pathlib.Path) -> Store:
    """A scaffolded store at `path`, with git initialised, two themes and their evidence.

    Uses only Store's public API: append_claims for the evidence, write_theme (which calls
    render_theme_body for the body and rebuilds layer 1 as a side effect), and one explicit
    rebuild_index so the index on disk is never just an accident of write order.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)],
                   check=True, capture_output=True, text=True)
    store = Store(path)
    (path / "ROUTER.md").write_text(
        "---\nschema_version: \"1.0.0\"\nowner: ai-operations\nsource: pipeline\n"
        "last_verified: 2026-09-14\nrun_id: %s\n---\n\n# ROUTER\n" % RUN_ID,
        encoding="utf-8",
    )
    store.append_claims(INGEST_RUN, [CLAIM_RENEWAL, CLAIM_IMPORT])
    store.write_theme(THEME_RENEWAL, render_theme_body(THEME_RENEWAL, [CLAIM_RENEWAL]))
    store.write_theme(THEME_IMPORT, render_theme_body(THEME_IMPORT, [CLAIM_IMPORT]))
    store.rebuild_index(RUN_ID)
    return store


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "_manual_store"
    build_store(target)
    print("wrote a fixture store at %s" % target)
