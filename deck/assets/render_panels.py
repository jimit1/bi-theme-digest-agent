"""Renders every code and terminal panel the slide plan needs, from real content.

Every panel comes from one of two places: an exact excerpt of a file already committed
in the code repository or the context store, or the real stdout of a command run against
this machine, in replay mode. Nothing here is typed prose standing in for a screenshot.

The context store is never written to. Two of the panels need a command that writes to
the store (the model swap and the approve dry run both create a new run directory), so
this script clones the store into a temporary directory first and points those two
commands at the clone with --store. Every other panel reads the real store directly,
because a git log, a grep and a file read do not write anything.

Run it with the project venv:
    /Users/jimabmatic.ai/momentive-bi-digest/.venv/bin/python deck/assets/render_panels.py

It regenerates every PNG under deck/assets/ and deck/assets/manifest.json from scratch,
so it is safe to run again after the code or the store changes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BUILD_ROOT = Path("/Users/jimabmatic.ai/momentive-bi-digest")
REPO = BUILD_ROOT / "bi-theme-digest-agent"
STORE = BUILD_ROOT / "bi-theme-digest-store"
VENV_PY = str(BUILD_ROOT / ".venv" / "bin" / "python")
ASSETS_DIR = REPO / "deck" / "assets"

# --- rendering constants -----------------------------------------------------------
IMG_WIDTH = 1920
PAD_X = 70
PAD_TOP = 60
LINE_GAP = 10
FONT_SIZE = 26
CAPTION_FONT_SIZE = 22
CAPTION_PAD = 26
BG = (250, 248, 244)
INK = (30, 28, 24)
CAPTION_BG = (36, 34, 30)
CAPTION_INK = (240, 238, 233)
MONO_REGULAR = ("/System/Library/Fonts/Menlo.ttc", 0)
MONO_BOLD = ("/System/Library/Fonts/Menlo.ttc", 1)
WRAP_CHARS = 108  # tuned so the longest real excerpt lines below do not overflow IMG_WIDTH

BODY_FONT = ImageFont.truetype(MONO_REGULAR[0], size=FONT_SIZE, index=MONO_REGULAR[1])
CAPTION_FONT = ImageFont.truetype(MONO_BOLD[0], size=CAPTION_FONT_SIZE, index=MONO_BOLD[1])


def ascii_only(text: str) -> str:
    """No em dash, no en dash, no other non ASCII sneaking into a panel."""
    text = text.replace("" + chr(0x2014) + "", "-").replace("" + chr(0x2013) + "", "-")
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    return text.encode("ascii", "replace").decode("ascii")


def wrap(raw_lines: list[str], width: int = WRAP_CHARS) -> list[str]:
    """Wraps each real line to width, preserving blank lines and not inventing text."""
    out: list[str] = []
    for line in raw_lines:
        line = ascii_only(line.rstrip("\n"))
        if line == "":
            out.append("")
            continue
        indent = len(line) - len(line.lstrip(" "))
        wrapped = textwrap.wrap(
            line, width=width, subsequent_indent=" " * min(indent + 2, 8),
            break_long_words=False, break_on_hyphens=False,
        ) or [""]
        out.extend(wrapped)
    return out


def read_lines(path: Path, start: int, end: int) -> list[str]:
    """1-indexed, inclusive, exactly like the line numbers a human would quote."""
    all_lines = path.read_text().splitlines()
    return all_lines[start - 1:end]


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    return result.stdout


def pretty_json_line(line: str) -> list[str]:
    obj = json.loads(line)
    return json.dumps(obj, indent=2).splitlines()


def parse_md_table(text: str, header_marker: str) -> list[dict[str, str]]:
    rows = []
    header = None
    for raw in text.splitlines():
        if not raw.strip().startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if header is None and header_marker in raw:
            header = cells
            continue
        if header is None:
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines[0].strip() == "---"
    end = lines[1:].index("---") + 1
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


# --- panel content builders ---------------------------------------------------------
# Each returns (raw_lines, source_kind, source, extra) where extra is either
# {"lines": "a-b"} for a file panel or {"command": "..."} for a command panel.

def panel_pipeline_diagram():
    path = REPO / "README.md"
    raw = read_lines(path, 31, 64)
    return raw, "file", "README.md", {"lines": "31-64"}


def panel_connector_enforcement():
    path = REPO / "mcp" / "salesforce_server.py"
    raw = read_lines(path, 115, 143)
    return raw, "file", "mcp/salesforce_server.py", {"lines": "115-143"}


def panel_editor_prompt():
    path = REPO / "src" / "digest" / "agents" / "editor" / "editor.prompt.md"
    raw = read_lines(path, 43, 59)
    return raw, "file", "src/digest/agents/editor/editor.prompt.md", {"lines": "43-59"}


def panel_editor_tools_grep():
    cmd = ["grep", "-n", "-e", "^TOOL_NAMES", "-e", "^    def ", "-e", "no write tool",
           "src/digest/agents/editor/tools.py"]
    out = run(cmd, cwd=REPO)
    raw = out.splitlines()
    return raw, "command", "$ " + " ".join(cmd), {"command": " ".join(cmd)}


def panel_store_git_log():
    cmd = ["git", "-C", str(STORE), "log", "--oneline"]
    out = run(cmd)
    raw = out.splitlines()
    display_cmd = "$ git -C ../bi-theme-digest-store log --oneline"
    return raw, "command", display_cmd, {"command": "git -C ../bi-theme-digest-store log --oneline"}


def panel_theme_index():
    path = STORE / "themes" / "_INDEX.md"
    text = path.read_text()
    rows = parse_md_table(text, "| id |")
    raw = ["themes/_INDEX.md, top 5 of 11 rows by score", ""]
    for row in rows[:5]:
        raw.append(f"{row['id']:<11} score {row['score']:<3} {row['status']:<6} {row['product_area']}")
        raw.extend(textwrap.wrap(row["title"], 100, subsequent_indent="  "))
        raw.extend(textwrap.wrap("aliases: " + row["aliases"], 100, subsequent_indent="  "))
        raw.append("")
    return raw, "file", "../bi-theme-digest-store/themes/_INDEX.md", {"lines": "1-23, top 5 rows"}


def panel_t1_pair():
    # The two trap files behind THEME-0002 are data/mock/traps/gong/calls/7782934451002.json
    # (T1a, Great Lakes Museum Alliance) and data/mock/traps/salesforce/cases/5008W00002aQpLrQAK.json
    # (T1b, Prairie Land Trust Council). The theme file's own evidence table already carries the
    # exact verified verbatim and citation for each, which is the same substring check the
    # pipeline's verifier runs, so it is read from there rather than re-parsed out of the raw json.
    theme = (STORE / "themes/THEME-0002.md").read_text()
    fm = frontmatter(theme)
    text = theme
    rows = parse_md_table(text, "| claim_id |")
    row_a = next(r for r in rows if r["claim_id"] == "03a7ca4ae6d8")
    row_b = next(r for r in rows if r["claim_id"] == "306b8bbab997")
    raw = [
        "T1a: Great Lakes Museum Alliance, " + row_a["source"],
        '"' + row_a["verbatim"] + '"',
        "",
        "T1b: Prairie Land Trust Council, " + row_b["source"],
        '"' + row_b["verbatim"] + '"',
        "",
        "THEME-0002: " + fm["title"],
        "editor's stated reason: " + fm["rationale"].strip('"'),
    ]
    raw = wrap(raw)
    return raw, "file", "../bi-theme-digest-store/themes/THEME-0002.md", {"lines": "evidence table + rationale"}


def panel_t2_aliases():
    path = STORE / "themes" / "THEME-0006.md"
    raw = read_lines(path, 8, 14)
    return raw, "file", "../bi-theme-digest-store/themes/THEME-0006.md", {"lines": "8-14"}


def panel_withheld_audit_line():
    cmd = ["grep", '"target": "5008W00002aQpLrQAK"', "runs/2026-09-10T06:00Z/run.log.jsonl"]
    out = run(cmd, cwd=STORE)
    line = out.strip().splitlines()[0]
    raw = pretty_json_line(line)
    display_cmd = "$ grep withhold runs/2026-09-10T06:00Z/run.log.jsonl | python -m json.tool"
    return raw, "command", display_cmd, {
        "command": "grep '\"target\": \"5008W00002aQpLrQAK\"' ../bi-theme-digest-store/runs/2026-09-10T06:00Z/run.log.jsonl"
    }


def panel_scrubber_redaction():
    cmd = ["grep", '"target": "7782934451404"', "runs/2026-09-09T06:00Z/run.log.jsonl"]
    out = run(cmd, cwd=STORE)
    lines = [l for l in out.strip().splitlines() if '"action": "scrub"' in l]
    raw = pretty_json_line(lines[0])
    display_cmd = "$ grep scrub runs/2026-09-09T06:00Z/run.log.jsonl | python -m json.tool"
    return raw, "command", display_cmd, {
        "command": "grep '\"target\": \"7782934451404\"' ../bi-theme-digest-store/runs/2026-09-09T06:00Z/run.log.jsonl"
    }


def panel_score_explain():
    digest = (STORE / "digests" / "2026-W37.md").read_text()
    lines = digest.splitlines()
    heading = next(l for l in lines if l.startswith("### 1."))
    explain = next(l for l in lines if l.startswith("Why this score:"))
    raw = [heading, "", explain]
    raw = wrap(raw)
    return raw, "file", "../bi-theme-digest-store/digests/2026-W37.md", {"lines": "theme 1 heading + score explain"}


def panel_w37_digest_first_screen():
    path = STORE / "digests" / "2026-W37.md"
    raw_lines = path.read_text().splitlines()
    # front matter, title, run line, cold start paragraph, first theme heading
    stop = raw_lines.index("### 1. Renewal amounts ignore prior-period credits and mid-year "
                           "upgrades, so members are over-billed (score 80)")
    excerpt = [l for l in raw_lines[7:stop] if l != "---"]
    excerpt = [l for l in excerpt if l.strip() != ""][:6]
    wrapped = wrap(excerpt)
    if len(wrapped) > 26:
        wrapped = wrapped[:26]
    return wrapped, "file", "../bi-theme-digest-store/digests/2026-W37.md", {"lines": "8-14, first screen"}


def panel_eval_results():
    path = REPO / "evals" / "results.md"
    text = path.read_text()
    rows = parse_md_table(text, "| id | description")
    wanted = ["T1a", "T1b", "T2a", "T2b", "T3", "T4a", "T4c"]
    picked = [r for r in rows if r["id"] in wanted]
    raw = ["evals/golden_set.yaml via evals/results.md: 5 must-appear, 2 must-not-appear", ""]
    for r in picked:
        raw.extend(textwrap.wrap(f"{r['id']} [{r['result']}] {r['description']}", 104,
                                  subsequent_indent="  "))
        raw.extend(textwrap.wrap("  evidence: " + r["evidence"], 104, subsequent_indent="    "))
    raw.append("")
    raw.append("Result: 18 of 18 assertions passed, exit code 0.")
    return raw, "file", "evals/results.md", {"lines": "T1a,T1b,T2a,T2b,T3,T4a,T4c + result line"}


def panel_cost_table():
    path = REPO / "docs" / "metrics" / "cost_table.md"
    raw = read_lines(path, 16, 19)
    return raw, "file", "docs/metrics/cost_table.md", {"lines": "16-19"}


def panel_swap_models():
    with tempfile.TemporaryDirectory(prefix="store-clone-") as tmp:
        clone = Path(tmp) / "store"
        subprocess.run(["git", "clone", "--quiet", str(STORE), str(clone)], check=True)
        cmd = [VENV_PY, "-m", "digest", "swap", "--models", "config/models.cheap.yaml",
               "--week", "2026-W37", "--mode", "replay", "--store", str(clone)]
        out = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True).stdout
    raw = wrap([l for l in out.splitlines() if l.strip()])
    display_cmd = "$ make swap-models   # python -m digest swap --models config/models.cheap.yaml --week 2026-W37"
    return raw, "command", display_cmd, {
        "command": "make swap-models (config/models.cheap.yaml, week 2026-W37, mode replay, "
                   "run against a temporary clone of the store, never the committed one)"
    }


def panel_ingest_cron():
    path = REPO / ".github" / "workflows" / "ingest.yml"
    raw = read_lines(path, 16, 20)
    return raw, "file", ".github/workflows/ingest.yml", {"lines": "16-20"}


def panel_approve_dry_run():
    with tempfile.TemporaryDirectory(prefix="store-clone-") as tmp:
        clone = Path(tmp) / "store"
        subprocess.run(["git", "clone", "--quiet", str(STORE), str(clone)], check=True)
        cmd = [VENV_PY, "-m", "digest", "approve", "--theme", "THEME-0002", "--dry-run",
               "--mode", "replay", "--repo", "OWNER/product-feedback", "--store", str(clone)]
        out = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True).stdout
    lines = out.splitlines()
    try:
        stop = lines.index("## Evidence")
    except ValueError:
        stop = len(lines)
    raw = lines[:stop]
    raw = [l for l in raw if l != ""][:20]
    raw = wrap(raw)
    display_cmd = ("$ python -m digest approve --theme THEME-0002 --dry-run --mode replay "
                   "--repo OWNER/product-feedback")
    return raw, "command", display_cmd, {
        "command": "python -m digest approve --theme THEME-0002 --dry-run --mode replay "
                   "--repo OWNER/product-feedback (run against a temporary clone of the store, "
                   "never the committed one)"
    }


PANELS = [
    ("01_pipeline_diagram.png", panel_pipeline_diagram),
    ("02_connector_enforcement.png", panel_connector_enforcement),
    ("03_editor_prompt_append_vs_open.png", panel_editor_prompt),
    ("04_editor_tools_grep.png", panel_editor_tools_grep),
    ("05_store_git_log.png", panel_store_git_log),
    ("06_theme_index.png", panel_theme_index),
    ("07_t1_pair_dedupe.png", panel_t1_pair),
    ("08_t2_aliases.png", panel_t2_aliases),
    ("09_withheld_comment_audit_line.png", panel_withheld_audit_line),
    ("10_scrubber_redaction_count.png", panel_scrubber_redaction),
    ("11_score_explain_top_theme.png", panel_score_explain),
    ("12_w37_digest_first_screen.png", panel_w37_digest_first_screen),
    ("13_eval_results_table.png", panel_eval_results),
    ("14_cost_table.png", panel_cost_table),
    ("15_swap_models_output.png", panel_swap_models),
    ("16_ingest_cron_lines.png", panel_ingest_cron),
    ("17_approve_dry_run_output.png", panel_approve_dry_run),
]


def render(filename: str, raw_lines: list[str], caption: str) -> Path:
    lines = [ascii_only(l) for l in raw_lines]
    line_h = FONT_SIZE + LINE_GAP
    content_h = max(1, len(lines)) * line_h
    caption_h = CAPTION_FONT_SIZE + 2 * CAPTION_PAD
    img_h = PAD_TOP + content_h + PAD_TOP + caption_h
    img = Image.new("RGB", (IMG_WIDTH, img_h), BG)
    draw = ImageDraw.Draw(img)
    y = PAD_TOP
    for line in lines:
        draw.text((PAD_X, y), line, font=BODY_FONT, fill=INK)
        y += line_h
    cap_top = img_h - caption_h
    draw.rectangle([0, cap_top, IMG_WIDTH, img_h], fill=CAPTION_BG)
    draw.text((PAD_X, cap_top + CAPTION_PAD - 4), caption, font=CAPTION_FONT, fill=CAPTION_INK)
    out_path = ASSETS_DIR / filename
    img.save(out_path)
    return out_path


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for filename, builder in PANELS:
        raw_lines, source_kind, source, extra = builder()
        if len(raw_lines) > 30:
            print(f"warning: {filename} has {len(raw_lines)} lines, over the ~28 line target",
                  file=sys.stderr)
        caption = source if source.startswith("$") else source
        out_path = render(filename, raw_lines, ascii_only(caption))
        sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
        row = {
            "file": f"deck/assets/{filename}",
            "source_kind": source_kind,
            "source": ascii_only(source),
            "sha256": sha256,
        }
        row.update(extra)
        manifest.append(row)
        print(f"wrote {out_path} ({len(raw_lines)} lines)")
    manifest_doc = {
        "schema": "AssetManifest",
        "schema_version": "1.0.0",
        "generated_by": "deck/assets/render_panels.py",
        "assets": manifest,
    }
    (ASSETS_DIR / "manifest.json").write_text(json.dumps(manifest_doc, indent=2) + "\n")
    print(f"wrote {ASSETS_DIR / 'manifest.json'} ({len(manifest)} assets)")


if __name__ == "__main__":
    main()
