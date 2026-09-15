"""The human approval gate: refusal, dry run and a monkeypatched `gh`.

The real `gh` CLI is never invoked here. Every test that reaches the filing path replaces
`digest.gate.subprocess.run` with a fake that records the exact argv and returns a fake
issue url, per `build/COMMON_RULES.md` rule 12 and the brief for B15.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from digest import gate  # noqa: E402
from digest.audit import Audit  # noqa: E402
from digest.errors import ContractViolation, GateRefused  # noqa: E402
from digest.store import Store, render_theme_body  # noqa: E402

RUN_ID = "2026-09-14T07:00Z"
WEEK = "2026-W37"
THEME_ID = "THEME-0001"
REPO_NAME = "owner/repo"


class _FakeGh:
    """Stands in for the `subprocess` module inside `digest.gate` only.

    `digest.gate` and `digest.store` both `import subprocess`, so patching `subprocess.run`
    itself would also redirect the store's real git calls into the fake. Replacing the name
    `subprocess` inside `gate`'s own namespace keeps the git calls the store fixture depends
    on (init, commit) hitting the real binary while every `gh` call goes to the fake.
    """

    def __init__(self, run_fn):
        self.run = run_fn


def _patch_gh(monkeypatch: pytest.MonkeyPatch, run_fn) -> None:
    monkeypatch.setattr(gate, "subprocess", _FakeGh(run_fn))


def _theme() -> dict:
    return {
        "schema_version": "1.0.0",
        "theme_id": THEME_ID,
        "title": "Renewal invoices do not show prior dues credit",
        "aliases": ["dues proration"],
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
        "score": 74,
        "score_inputs": {
            "distinct_customers": 1, "distinct_prospects": 0, "arr_sum": 340000,
            "open_cases": 1, "recency_days": 1, "claim_count": 1, "high_importance_count": 1,
        },
        "rationale": "One customer raised a renewal credit gap that finance corrects by hand.",
        "stale": False,
        "stale_reason": None,
        "last_evidence_at": "2026-09-10T14:22:05.000Z",
        "proposal_id": "%s/%s" % (WEEK, THEME_ID),
        "filed_issue_url": None,
    }


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """A scaffolded store with one open theme and one proposed proposal for it."""
    monkeypatch.delenv("DIGEST_STORE_READONLY", raising=False)
    monkeypatch.delenv("DIGEST_STORE_PUSH", raising=False)
    monkeypatch.delenv(gate.REPO_ENV, raising=False)
    root = tmp_path / "bi-theme-digest-store"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   capture_output=True, text=True)
    s = Store(root)
    (root / "ROUTER.md").write_text("---\nschema_version: \"1.0.0\"\n---\n\n# ROUTER\n",
                                    encoding="utf-8")
    s.write_theme_index([], RUN_ID)
    theme = _theme()
    s.write_theme(theme, render_theme_body(theme, []))
    s.write_proposal(
        THEME_ID, WEEK, RUN_ID, "Renewal invoices do not show prior dues credit",
        "One customer reported the renewal invoice arrives with no line for dues already paid.",
        "One high importance customer, a manual finance workaround every renewal.",
    )
    s.commit("build %s digest" % WEEK, RUN_ID)
    return s


# ----------------------------------------------------------------- write_proposals


def test_write_proposals_resolves_placeholders_and_leaves_status_proposed(
    store: Store,
) -> None:
    proposal = {
        "file_proposals": [
            {
                "theme_id_or_placeholder": "NEW-1",
                "title": "New theme filed straight away",
                "body": "The body.",
                "reason": "The reason.",
            },
        ],
    }
    paths = gate.write_proposals(WEEK, RUN_ID, proposal, {"NEW-1": "THEME-0002"}, store)
    assert paths == [store.path / "proposals" / WEEK / "THEME-0002.md"]
    records = gate.list_proposals(store, week=WEEK)
    by_id = {r["theme_id"]: r for r in records}
    assert by_id["THEME-0002"]["status"] == "proposed"
    assert by_id["THEME-0002"]["filed_issue_url"] is None


def test_list_proposals_with_no_week_reads_every_week_on_disk(store: Store) -> None:
    store.write_proposal("THEME-0001", "2026-W38", RUN_ID, "t", "b", "r")
    records = gate.list_proposals(store)
    weeks = {r["week"] for r in records}
    assert weeks == {"2026-W37", "2026-W38"}


# ----------------------------------------------------------------- refusal


def test_refuses_without_yes(store: Store) -> None:
    with pytest.raises(GateRefused) as caught:
        gate.approve(THEME_ID, yes=False, repo=REPO_NAME, store=store)
    assert str(caught.value) == "--yes required"


def test_refuses_without_a_repo(store: Store) -> None:
    with pytest.raises(GateRefused) as caught:
        gate.approve(THEME_ID, yes=True, repo=None, store=store)
    assert "--repo" in str(caught.value)


def test_repo_from_env_var_is_accepted(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gate.REPO_ENV, REPO_NAME)
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured.setdefault("calls", []).append(argv)
        if argv[:3] == ["gh", "issue", "create"]:
            return subprocess.CompletedProcess(argv, 0, stdout="https://x.invalid/1\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    _patch_gh(monkeypatch, fake_run)
    url = gate.approve(THEME_ID, yes=True, repo=None, store=store)
    assert url == "https://x.invalid/1"
    assert "--repo" in captured["calls"][-1]
    assert captured["calls"][-1][captured["calls"][-1].index("--repo") + 1] == REPO_NAME


# ----------------------------------------------------------------- dry run


def test_dry_run_prints_and_files_nothing(
    store: Store, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_run(argv, **kwargs):
        raise AssertionError("gh must not be called in a dry run: %r" % (argv,))

    _patch_gh(monkeypatch, fail_run)
    result = gate.approve(THEME_ID, yes=True, repo=REPO_NAME, store=store, dry_run=True)
    assert result is None

    out = capsys.readouterr().out
    assert THEME_ID in out
    assert "## Evidence" in out
    assert "digest approve --yes" in out

    proposal_path = store.path / "proposals" / WEEK / ("%s.md" % THEME_ID)
    text = proposal_path.read_text(encoding="utf-8")
    assert "status: proposed" in text
    assert "filed_issue_url: null" in text
    theme, _body = store.read_theme(THEME_ID)
    assert theme["status"] == "open"
    assert theme["filed_issue_url"] is None


# ----------------------------------------------------------------- filing


def test_missing_proposal_is_a_contract_violation(store: Store) -> None:
    with pytest.raises(ContractViolation):
        gate.approve("THEME-0099", yes=True, repo=REPO_NAME, store=store)


def test_monkeypatched_gh_records_argv_and_files_correctly(
    store: Store, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    captured_body: dict[str, str] = {}
    fake_url = "https://github.example.invalid/owner/repo/issues/42"

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if argv[:3] == ["gh", "label", "create"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[:3] == ["gh", "issue", "create"]:
            body_file = argv[argv.index("--body-file") + 1]
            captured_body["text"] = Path(body_file).read_text(encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout=fake_url + "\n", stderr="")
        raise AssertionError("unexpected gh call: %r" % (argv,))

    _patch_gh(monkeypatch, fake_run)
    audit = Audit(RUN_ID, store.path)

    url = gate.approve(THEME_ID, yes=True, repo=REPO_NAME, store=store, audit=audit)
    assert url == fake_url

    # Exactly the two gh calls, label first, in argv list form, never shell=True.
    assert len(calls) == 2
    assert calls[0] == ["gh", "label", "create", gate.LABEL, "--repo", REPO_NAME, "--force"]
    issue_call = calls[1]
    assert issue_call[:3] == ["gh", "issue", "create"]
    assert issue_call[3:5] == ["--repo", REPO_NAME]
    assert issue_call[5] == "--title"
    assert issue_call[6].startswith(THEME_ID)
    assert issue_call[7] == "--body-file"
    assert issue_call[9:] == ["--label", gate.LABEL]

    body = captured_body["text"]
    assert "One customer reported the renewal invoice" in body
    assert "## Evidence" in body
    assert ("Filed from theme digest %s, run %s, approved by a human with "
            "`digest approve --yes`." % (WEEK, RUN_ID)) in body

    proposal_path = store.path / "proposals" / WEEK / ("%s.md" % THEME_ID)
    proposal_text = proposal_path.read_text(encoding="utf-8")
    assert "status: filed" in proposal_text
    assert 'filed_issue_url: "%s"' % fake_url in proposal_text

    theme, _body = store.read_theme(THEME_ID)
    assert theme["status"] == "filed"
    assert theme["filed_issue_url"] == fake_url

    approve_events = [e for e in audit.events() if e["action"] == "approve"]
    assert approve_events[-1]["outcome"] == "ok"
    assert approve_events[-1]["detail"]["filed_issue_url"] == fake_url

    log = subprocess.run(
        ["git", "-C", str(store.path), "log", "--format=%s", "-1"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert log == "run %s: approve %s filed %s" % (RUN_ID, THEME_ID, fake_url)


def test_refusal_without_yes_logs_a_withheld_audit_event(store: Store) -> None:
    audit = Audit(RUN_ID, store.path)
    with pytest.raises(GateRefused):
        gate.approve(THEME_ID, yes=False, repo=REPO_NAME, store=store, audit=audit)
    events = [e for e in audit.events() if e["action"] == "approve"]
    assert events[-1]["outcome"] == "withheld"
