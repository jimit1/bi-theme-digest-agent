"""The human approval gate.

This module is the only code path in the package that can create anything outside the
store: it is the one place that shells out to `gh` to file a GitHub issue. Every other
module writes only inside the context store repository. An editor proposes a theme or a
filing; code writes the proposal to disk with `status: proposed`; nothing files an issue
until a human runs `digest approve --yes`, and even then the filing itself happens here and
nowhere else.

`write_proposals` turns one `EditorProposal.file_proposals` list into files on disk, with
placeholders already resolved through `theme_id_map` (the mapping `allocate_theme_ids`
returned for this run). `approve` is the gate itself: it refuses without `--yes`, refuses
without a repo, and otherwise files the issue, marks the proposal and the theme `filed`, logs
one audit event and commits the store. `list_proposals` is a thin read helper used by both
the CLI and by `approve` to find a proposal by theme id without already knowing its week.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from digest.errors import ContractViolation, GateRefused
from digest.store import Store

__all__ = ["write_proposals", "list_proposals", "approve"]

REPO_ENV = "DIGEST_ISSUES_REPO"
LABEL = "theme-digest"

_STATUS_RE = re.compile(r"^status: proposed$", re.MULTILINE)
_URL_RE = re.compile(r"^filed_issue_url: null$", re.MULTILINE)


def write_proposals(
    week: str,
    run_id: str,
    proposal: dict[str, Any],
    theme_id_map: dict[str, str],
    store: Store,
) -> list[Path]:
    """Write one file per `proposal["file_proposals"]` entry, `status: proposed`.

    `theme_id_map` resolves a `NEW-n` placeholder to the real `THEME-nnnn` the store
    allocated for this run. An entry that already names an existing `THEME-nnnn` is passed
    through unchanged. The store validates and writes; this function resolves nothing else.
    """
    written: list[Path] = []
    for entry in proposal.get("file_proposals", []):
        ref = entry["theme_id_or_placeholder"]
        theme_id = theme_id_map.get(ref, ref)
        path = store.write_proposal(
            theme_id, week, run_id, entry["title"], entry["body"], entry["reason"],
        )
        written.append(path)
    return written


def list_proposals(store: Store, week: str | None = None) -> list[dict[str, Any]]:
    """Every proposal for one week, or for every week on disk when `week` is None."""
    if week is not None:
        return store.read_proposals(week)
    proposals_dir = store.path / "proposals"
    out: list[dict[str, Any]] = []
    if proposals_dir.is_dir():
        for week_name in sorted(p.name for p in proposals_dir.iterdir() if p.is_dir()):
            out.extend(store.read_proposals(week_name))
    return out


def _find_proposal(store: Store, theme_id: str) -> dict[str, Any] | None:
    for record in list_proposals(store):
        if record.get("theme_id") == theme_id:
            return record
    return None


def _issue_title(theme_id: str, body: str) -> str:
    first_line = body.strip("\n").split("\n", 1)[0]
    title_text = first_line.lstrip("#").strip()
    return "%s: %s" % (theme_id, title_text) if title_text else theme_id


def _evidence_table(theme_body: str) -> str:
    marker = "## Evidence\n\n"
    index = theme_body.find(marker)
    if index == -1:
        return "(no evidence recorded on the theme)"
    return theme_body[index + len(marker):].strip("\n")


def _mark_proposal_filed(path: str, url: str) -> None:
    """Move a proposal file's frontmatter from proposed/null to filed/url, in place.

    There is no store method for this: write_proposal always writes status proposed and
    filed_issue_url null, on purpose, because filing is a human action. This targets exactly
    the two fixed lines the store's own writer produces, so the rest of the frontmatter and
    the body are untouched.
    """
    text = Path(path).read_text(encoding="utf-8")
    text, replaced_status = _STATUS_RE.subn("status: filed", text, count=1)
    text, replaced_url = _URL_RE.subn('filed_issue_url: "%s"' % url, text, count=1)
    if not replaced_status or not replaced_url:
        raise ContractViolation(
            "EditorProposal",
            ["proposal at %s is not in the expected proposed status with no filed url" % path],
        )
    Path(path).write_text(text, encoding="utf-8")


def approve(
    theme_id: str,
    *,
    yes: bool,
    repo: str | None,
    store: Store,
    dry_run: bool = False,
    audit: Any = None,
) -> str | None:
    """File the GitHub issue for one proposed theme. Code performs every write, the human
    only supplies `--yes`.

    Raises `GateRefused("--yes required")` when `yes` is false. Raises `GateRefused` naming
    the `--repo` flag when neither `repo` nor `DIGEST_ISSUES_REPO` resolves to a value. With
    `dry_run=True`, prints the issue title and body and files nothing, and returns None.
    Otherwise files the issue with `gh`, marks the proposal and the theme `filed`, logs one
    `approve` audit event and commits the store, returning the filed issue url.
    """
    if not yes:
        if audit is not None:
            audit.log(agent="gate", action="approve", stage="propose", target=theme_id,
                      outcome="withheld", detail={"reason": "--yes required"})
        raise GateRefused()

    resolved_repo = repo or os.environ.get(REPO_ENV)
    if not resolved_repo:
        raise GateRefused("--repo required (or set %s)" % REPO_ENV)

    if audit is not None:
        store.attach_audit(audit)

    record = _find_proposal(store, theme_id)
    if record is None:
        raise ContractViolation("EditorProposal", ["no proposal on file for %s" % theme_id])

    week = record["week"]
    proposal_run_id = record["run_id"]
    theme, theme_body = store.read_theme(theme_id)

    title = _issue_title(theme_id, record["body"])
    evidence = _evidence_table(theme_body)
    footer = (
        "Filed from theme digest %s, run %s, approved by a human with `digest approve --yes`."
        % (week, proposal_run_id)
    )
    issue_body = "%s\n\n## Evidence\n\n%s\n\n%s\n" % (record["body"].strip("\n"), evidence, footer)

    if dry_run:
        print(title)
        print(issue_body)
        return None

    # Best effort: the label may already exist, and a failure here must not block filing.
    subprocess.run(
        ["gh", "label", "create", LABEL, "--repo", resolved_repo, "--force"],
        capture_output=True, text=True, check=False,
    )

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(issue_body)
            tmp_path = handle.name
        result = subprocess.run(
            ["gh", "issue", "create", "--repo", resolved_repo, "--title", title,
             "--body-file", tmp_path, "--label", LABEL],
            check=True, capture_output=True, text=True,
        )
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    url = result.stdout.strip().splitlines()[-1].strip()

    _mark_proposal_filed(record["path"], url)

    theme["status"] = "filed"
    theme["filed_issue_url"] = url
    store.write_theme(theme, theme_body)

    if audit is not None:
        audit.log(agent="gate", action="approve", stage="propose", target=theme_id,
                  outcome="ok", detail={"filed_issue_url": url})

    store.commit("run %s: approve %s filed %s" % (proposal_run_id, theme_id, url), proposal_run_id)

    return url
