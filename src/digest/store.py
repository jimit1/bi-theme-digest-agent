"""The context store client: the only thing in this package that writes to the store repo.

The store is a second repository with no code in it, so its `git log` is an audit trail
rather than a changelog. Everything here writes files into that repository and commits
them with a fixed author identity. Nothing here is written by a model: an agent produces a
validated document, code turns it into a file.

Three things worth knowing before reading further.

Layer 1 is derived, never edited. `themes/_INDEX.md` is regenerated from the theme files on
every theme write, so the index and the themes cannot drift apart. `rebuild_index()` is the
same operation on demand.

The store never sees unscrubbed text. `write_source_document` refuses a SourceDocument whose
`scrubbed` flag is not true, and there is no other entry point that writes source text, so
"nothing in this repository is raw" is enforced by the absence of an API rather than by a
convention.

A commit is skipped, not failed, when there is no git directory or DIGEST_STORE_READONLY=1.
The demo has to be green on a laptop with no credential configured, so the skip is recorded
as one audit event with outcome withheld and `commit` returns None.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Literal, TypedDict

import yaml

from digest.contracts import schema_version, validate
from digest.errors import ContractViolation

__all__ = [
    "Store",
    "ThemeIndexLine",
    "STORE_FRONTMATTER_KEYS",
    "THEME_INDEX_LINE_RE",
    "SOURCE_ROW_RE",
    "COMMIT_AUTHOR",
    "DEFAULT_OWNER",
    "render_theme_body",
    "source_ref_label",
    "mmss",
]

# --------------------------------------------------------------------------- constants

DEFAULT_OWNER = "ai-operations"
COMMIT_AUTHOR_NAME = "bi-theme-digest-agent"
COMMIT_AUTHOR_EMAIL = "agent@example.invalid"
COMMIT_AUTHOR = "%s <%s>" % (COMMIT_AUTHOR_NAME, COMMIT_AUTHOR_EMAIL)
READONLY_ENV = "DIGEST_STORE_READONLY"
PUSH_ENV = "DIGEST_STORE_PUSH"

# The five StoreFrontmatter keys, first and in this order, on every stored markdown file.
STORE_FRONTMATTER_KEYS = ("schema_version", "owner", "source", "last_verified", "run_id")

# file_formats.md section 4. The regex is the definition of a theme index line.
THEME_INDEX_LINE_RE = re.compile(
    r"^\| (THEME-\d{4}) \| ([^|\n]{1,200}) \| "
    r"(membership|events|fundraising|lms|jobs|accounting|integrations|reporting) \| "
    r"(open|quiet|filed) \| (\d{1,3}) \| (\d+) \| (\d+) \| "
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z) \| ([^|\n]{0,400}) \|$"
)

THEME_INDEX_HEADER = (
    "| id | title | product_area | status | score | accounts | evidence | "
    "last_updated_run | aliases |"
)
THEME_INDEX_SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"

# file_formats.md section 6.
SOURCE_ROW_RE = re.compile(
    r"^\| (gong|salesforce) \| ([A-Za-z0-9]{1,40}) \| (ACC-\d{4}) \| (call|case) \| "
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})) \| "
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z) \| (\d+) \| (\d+) \|$"
)

SOURCE_INDEX_HEADER = (
    "| source | source_id | account_id | doc_type | occurred_at | ingest_run | turns | withheld |"
)
SOURCE_INDEX_SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- |"

WATERMARK_RUN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")
WATERMARK_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

# The scaffold carries a date so that one frontmatter reader serves every file in the
# repository from the first commit onwards. It is the pinned build date of week 37.
SCAFFOLD_DAY = "2026-09-14"
SCAFFOLD_RUN_ID = "2026-09-14T07:00Z"

_INGEST_SUFFIX = "T06:00Z"


class ThemeIndexLine(TypedDict):
    theme_id: str
    title: str
    product_area: str
    status: Literal["open", "quiet", "filed"]
    score: int
    accounts_count: int
    evidence_count: int
    last_updated_run: str
    aliases: list[str]


# --------------------------------------------------------------------------- yaml helpers


class _PlainLoader(yaml.SafeLoader):
    """SafeLoader with the implicit timestamp resolver removed.

    Every date in this system is a pattern checked string in a schema. If YAML turned
    `last_verified: 2026-09-14` into a datetime.date on the way in, the document would stop
    validating against its own contract on the way back out.
    """


_PlainLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

# Keys always emitted in double quotes, so the frontmatter matches the contract examples
# byte for byte where those examples quote a value.
_ALWAYS_QUOTED = ("schema_version", "rationale", "reason")

_NEEDS_QUOTING = re.compile(
    r"^$|^[\s>|*&!%@`\[\]{}#'\"?-]|[:#]\s|\s$|\n|^(true|false|null|yes|no|on|off|~)$",
    re.IGNORECASE,
)
# Inside a flow list or flow mapping these end the item, so a value holding one is quoted.
_FLOW_SPECIALS = (",", "[", "]", "{", "}")


def _scalar(value: Any, key: str = "", flow: bool = False) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_scalar(item, flow=True) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join("%s: %s" % (k, _scalar(v, flow=True)) for k, v in value.items()) + "}"
    text = str(value)
    if (key in _ALWAYS_QUOTED
            or _NEEDS_QUOTING.search(text)
            or (flow and any(ch in text for ch in _FLOW_SPECIALS))):
        return json.dumps(text, ensure_ascii=False)
    return text


def _dump_frontmatter(mapping: dict[str, Any], key_order: Iterable[str]) -> str:
    seen: list[str] = []
    for key in key_order:
        if key in mapping and key not in seen:
            seen.append(key)
    for key in mapping:
        if key not in seen:
            seen.append(key)
    lines = ["---"]
    for key in seen:
        lines.append("%s: %s" % (key, _scalar(mapping[key], key)))
    lines.append("---")
    return "\n".join(lines) + "\n"


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body). A file with no frontmatter yields ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n")
    if parts[0].strip() != "---":
        return {}, text
    for index in range(1, len(parts)):
        if parts[index].strip() == "---":
            block = "\n".join(parts[1:index])
            body = "\n".join(parts[index + 1:])
            loaded = yaml.load(block, Loader=_PlainLoader) or {}
            if not isinstance(loaded, dict):
                raise ContractViolation("StoreFrontmatter", ["frontmatter is not a mapping"])
            return loaded, body.lstrip("\n")
    raise ContractViolation("StoreFrontmatter", ["frontmatter block is not closed"])


def _cell(text: Any) -> str:
    """A markdown table cell: no pipe, no newline. A pipe becomes a slash, as the contract says."""
    return str(text).replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def mmss(start_ms: int) -> str:
    """mm:ss with minutes continuing past 59 rather than rolling into hours."""
    minutes = start_ms // 60000
    seconds = (start_ms % 60000) // 1000
    return "%02d:%02d" % (minutes, seconds)


def source_ref_label(claim: dict[str, Any]) -> str:
    """`call <id> at mm:ss` or `case <number> comment <id>`, the citation a human can follow."""
    ref = claim.get("source_ref") or {}
    if "call_id" in ref:
        return "call %s at %s" % (ref["call_id"], mmss(int(ref.get("start_ms", 0))))
    return "case %s comment %s" % (ref.get("case_number", "?"), ref.get("comment_id", "?"))


def render_theme_body(theme: dict[str, Any], claims: Iterable[dict[str, Any]]) -> str:
    """The markdown body of a theme file: the rationale, then the evidence table.

    Code writes this, not the model. The model wrote the rationale and nothing else.
    """
    rows = [
        "| claim_id | account | source | moment | verbatim |",
        "| --- | --- | --- | --- | --- |",
    ]
    for claim in claims:
        moment = source_ref_label(claim)
        ref = claim.get("source_ref") or {}
        if "call_id" in ref and ref.get("speaker_name"):
            moment = "%s, %s" % (moment, ref["speaker_name"])
        rows.append(
            "| %s | %s | %s | %s | %s |"
            % (
                _cell(claim.get("claim_id", "")),
                _cell(claim.get("account_name", "")),
                _cell(claim.get("source", "")),
                _cell(moment),
                _cell(claim.get("verbatim", "")),
            )
        )
    return "## Why this matters\n\n%s\n\n## Evidence\n\n%s\n" % (
        theme.get("rationale", "").strip(),
        "\n".join(rows),
    )


# --------------------------------------------------------------------------- the store


class Store:
    """Read and write the context store repository."""

    def __init__(self, path: str | os.PathLike[str], audit: Any = None) -> None:
        self.path = Path(path)
        self.audit = audit

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Store(%r)" % str(self.path)

    def attach_audit(self, audit: Any) -> "Store":
        """Give the store a run log to write to. Returns self so it chains."""
        self.audit = audit
        return self

    @classmethod
    def clone_or_open(cls, url_or_path: str, dest: str | os.PathLike[str] | None = None) -> "Store":
        """Clone a URL into dest, or open a path that is already on disk."""
        if cls._is_url(url_or_path):
            if dest is None:
                raise ContractViolation("Store", ["clone_or_open needs a dest for a URL"])
            target = Path(dest)
            if not (target / ".git").exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", url_or_path, str(target)],
                               check=True, capture_output=True, text=True)
            return cls(target)
        return cls(Path(url_or_path))

    @staticmethod
    def _is_url(value: str) -> bool:
        return (
            value.startswith(("http://", "https://", "ssh://", "git://", "git@"))
            or (value.endswith(".git") and not Path(value).exists())
        )

    # -------------------------------------------------------------- paths

    @property
    def themes_dir(self) -> Path:
        return self.path / "themes"

    @property
    def theme_index_path(self) -> Path:
        return self.themes_dir / "_INDEX.md"

    @property
    def sources_dir(self) -> Path:
        return self.path / "sources"

    @property
    def sources_index_path(self) -> Path:
        return self.sources_dir / "_INDEX.md"

    def theme_path(self, theme_id: str) -> Path:
        return self.themes_dir / ("%s.md" % theme_id)

    def claims_path(self, run_id: str) -> Path:
        return self.path / "evidence" / "claims" / ("%s.jsonl" % run_id)

    def rejected_path(self, run_id: str) -> Path:
        return self.path / "evidence" / "rejected" / ("%s.jsonl" % run_id)

    def _log(self, **kwargs: Any) -> None:
        if self.audit is not None:
            self.audit.log(**kwargs)

    def _write_text(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    # -------------------------------------------------------------- layer 0 and 1

    def read_router(self) -> str:
        """Layer 0. Always read before anything else in the repository."""
        path = self.path / "ROUTER.md"
        self._log(agent="store", action="read", stage="store", target="ROUTER.md")
        return path.read_text(encoding="utf-8")

    def read_theme_index(self) -> list[ThemeIndexLine]:
        """Layer 1, parsed with the contract regex. A line that does not match is fatal."""
        path = self.theme_index_path
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        _frontmatter, body = _split_frontmatter(text)
        offset = text.count("\n", 0, len(text) - len(body)) if body else 0
        lines: list[ThemeIndexLine] = []
        errors: list[str] = []
        for number, raw in enumerate(body.split("\n"), start=offset + 1):
            line = raw.rstrip("\r")
            if not line.startswith("|"):
                continue
            if line == THEME_INDEX_HEADER or line == THEME_INDEX_SEPARATOR:
                continue
            match = THEME_INDEX_LINE_RE.match(line)
            if not match:
                errors.append("line %d does not match the theme index line format" % number)
                continue
            aliases_cell = match.group(9).strip()
            lines.append(
                ThemeIndexLine(
                    theme_id=match.group(1),
                    title=match.group(2).strip(),
                    product_area=match.group(3),
                    status=match.group(4),  # type: ignore[arg-type]
                    score=int(match.group(5)),
                    accounts_count=int(match.group(6)),
                    evidence_count=int(match.group(7)),
                    last_updated_run=match.group(8),
                    aliases=[] if aliases_cell == "-" else [a for a in aliases_cell.split("; ") if a],
                )
            )
        if errors:
            raise ContractViolation("ThemeIndexLine", errors)
        self._log(agent="store", action="read", stage="store", target="themes/_INDEX.md",
                  detail={"themes": len(lines)})
        return lines

    def write_theme_index(self, lines: list[ThemeIndexLine], run_id: str) -> None:
        """Write layer 1. Sorted score descending then theme_id ascending, pinned."""
        ordered = sorted(lines, key=lambda line: (-int(line["score"]), line["theme_id"]))
        rows = [THEME_INDEX_HEADER, THEME_INDEX_SEPARATOR]
        for line in ordered:
            aliases = [_cell(a) for a in line.get("aliases", [])]
            rows.append(
                "| %s | %s | %s | %s | %d | %d | %d | %s | %s |"
                % (
                    line["theme_id"],
                    _cell(line["title"]),
                    line["product_area"],
                    line["status"],
                    int(line["score"]),
                    int(line["accounts_count"]),
                    int(line["evidence_count"]),
                    line["last_updated_run"],
                    "; ".join(aliases) if aliases else "-",
                )
            )
        frontmatter = {
            "schema_version": schema_version("Theme"),
            "owner": DEFAULT_OWNER,
            "source": "synthesized",
            "last_verified": run_id[:10],
            "run_id": run_id,
        }
        text = _dump_frontmatter(frontmatter, STORE_FRONTMATTER_KEYS)
        text += "\n# Theme index\n\n" + "\n".join(rows) + "\n"
        self._write_text(self.theme_index_path, text)
        self._log(agent="store", action="write", stage="store", target="themes/_INDEX.md",
                  detail={"themes": len(ordered)})

    def rebuild_index(self, run_id: str | None = None) -> list[ThemeIndexLine]:
        """Regenerate layer 1 from the theme files themselves, so the two cannot drift."""
        lines: list[ThemeIndexLine] = []
        newest = run_id
        for path in sorted(self.themes_dir.glob("THEME-*.md")) if self.themes_dir.is_dir() else []:
            theme, _body = _split_frontmatter(path.read_text(encoding="utf-8"))
            lines.append(
                ThemeIndexLine(
                    theme_id=theme["theme_id"],
                    title=theme["title"],
                    product_area=theme["product_area"],
                    status=theme["status"],
                    score=int(theme["score"]),
                    accounts_count=len(theme.get("accounts") or []),
                    evidence_count=len(theme.get("evidence") or []),
                    last_updated_run=theme["last_updated_run"],
                    aliases=list(theme.get("aliases") or []),
                )
            )
            if newest is None or theme["last_updated_run"] > newest:
                newest = theme["last_updated_run"]
        if newest is None:
            existing, _body = _split_frontmatter(
                self.theme_index_path.read_text(encoding="utf-8")
            ) if self.theme_index_path.is_file() else ({}, "")
            newest = existing.get("run_id") or SCAFFOLD_RUN_ID
        self.write_theme_index(lines, newest)
        return lines

    # -------------------------------------------------------------- layer 2

    def read_theme(self, theme_id: str) -> tuple[dict[str, Any], str]:
        """(Theme frontmatter, markdown body). Validated on the way out of the file."""
        path = self.theme_path(theme_id)
        if not path.is_file():
            raise ContractViolation("Theme", ["no theme file at %s" % path])
        theme, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        validate(theme, "Theme")
        self._log(agent="store", action="read", stage="store", target=theme_id)
        return theme, body

    def write_theme(self, theme: dict[str, Any], body: str) -> Path:
        """Validate, write the file, then regenerate layer 1 from every theme on disk."""
        validate(theme, "Theme")
        order = list(STORE_FRONTMATTER_KEYS) + [
            key for key in _theme_key_order() if key not in STORE_FRONTMATTER_KEYS
        ]
        text = _dump_frontmatter(theme, order) + "\n" + body.strip("\n") + "\n"
        path = self._write_text(self.theme_path(theme["theme_id"]), text)
        self._log(agent="store", action="write", stage="store", target=theme["theme_id"],
                  detail={"evidence": len(theme.get("evidence") or [])})
        self.rebuild_index(theme["last_updated_run"])
        return path

    def allocate_theme_ids(self, placeholders: list[str]) -> dict[str, str]:
        """NEW-n to THEME-nnnn, continuing from the highest id in the index.

        Sorted by the numeric suffix so the same input produces the same ids on a rerun.
        That property is an eval assertion, not a hope.
        """
        highest = 0
        for line in self.read_theme_index():
            highest = max(highest, int(line["theme_id"].split("-")[1]))
        ordered = sorted(placeholders, key=lambda p: int(p.split("-")[1]))
        out: dict[str, str] = {}
        for offset, placeholder in enumerate(ordered, start=1):
            out[placeholder] = "THEME-%04d" % (highest + offset)
        return out

    # -------------------------------------------------------------- evidence

    def append_claims(self, run_id: str, claims: list[dict[str, Any]]) -> int:
        """Append validated claims to evidence/claims/<run_id>.jsonl. Append only."""
        return self._append(self.claims_path(run_id), claims, "Claim", run_id)

    def append_rejected(self, run_id: str, rejected: list[dict[str, Any]]) -> int:
        """Append validated rejections. A run with rejections is a normal run."""
        return self._append(self.rejected_path(run_id), rejected, "RejectedClaim", run_id)

    def _append(self, path: Path, docs: list[dict[str, Any]], schema: str, run_id: str) -> int:
        for index, doc in enumerate(docs):
            try:
                validate(doc, schema)
            except ContractViolation as exc:
                raise ContractViolation(
                    schema, ["item %d: %s" % (index, error) for error in exc.errors]
                ) from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for doc in docs:
                handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
            handle.flush()
        self._log(agent="store", action="write", stage="store",
                  target=str(path.relative_to(self.path)), detail={"count": len(docs)})
        return len(docs)

    def read_claims(self, run_ids: list[str] | None = None,
                    week: str | None = None) -> list[dict[str, Any]]:
        """Claims for the given run ids, or for a week resolved through the sources index."""
        if run_ids is None and week is not None:
            run_ids = self.ingest_runs_for_week(week)
        paths: list[Path]
        if run_ids is None:
            directory = self.path / "evidence" / "claims"
            paths = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
        else:
            paths = [self.claims_path(r) for r in run_ids]
        out: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                continue
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        self._log(agent="store", action="read", stage="store",
                  target="evidence/claims", detail={"files": len(paths), "claims": len(out)})
        return out

    def ingest_runs_for_week(self, week: str) -> list[str]:
        """The ingest run ids that belong to a week.

        Taken from the sources index when it has rows for that week, because that is the
        record of what was actually ingested. An empty index falls back to the Monday to
        Friday run ids the calendar pins, so a fresh store still answers the question.
        """
        match = WEEK_RE.match(week)
        if not match:
            raise ContractViolation("Week", ["%r is not a week label" % week])
        year, number = int(match.group(1)), int(match.group(2))
        found = {
            row["ingest_run"]
            for row in self.read_source_rows()
            if _iso_week(row["ingest_run"][:10]) == (year, number)
        }
        if found:
            return sorted(found)
        return [
            "%s%s" % (datetime.date.fromisocalendar(year, number, day).isoformat(), _INGEST_SUFFIX)
            for day in range(1, 6)
        ]

    # -------------------------------------------------------------- sources and watermark

    def read_watermark(self) -> tuple[str | None, datetime.date | None]:
        """(last_ingest_run, last_ingest_day) from the sources index frontmatter."""
        if not self.sources_index_path.is_file():
            return None, None
        frontmatter, _body = _split_frontmatter(
            self.sources_index_path.read_text(encoding="utf-8")
        )
        run = frontmatter.get("last_ingest_run")
        day = frontmatter.get("last_ingest_day")
        errors: list[str] = []
        if run is not None and not (isinstance(run, str) and WATERMARK_RUN_RE.match(run)):
            errors.append("last_ingest_run %r does not match the run id pattern" % run)
        if day is not None and not (isinstance(day, str) and WATERMARK_DAY_RE.match(day)):
            errors.append("last_ingest_day %r does not match the date pattern" % day)
        if errors:
            raise ContractViolation("StoreFrontmatter", errors)
        return run, (datetime.date.fromisoformat(day) if day else None)

    def read_source_rows(self) -> list[dict[str, Any]]:
        """Every row of the sources index, parsed with the contract regex."""
        if not self.sources_index_path.is_file():
            return []
        text = self.sources_index_path.read_text(encoding="utf-8")
        _frontmatter, body = _split_frontmatter(text)
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for number, raw in enumerate(body.split("\n"), start=1):
            line = raw.rstrip("\r")
            if not line.startswith("|"):
                continue
            if line in (SOURCE_INDEX_HEADER, SOURCE_INDEX_SEPARATOR):
                continue
            match = SOURCE_ROW_RE.match(line)
            if not match:
                errors.append("sources index line %d does not match the row format" % number)
                continue
            rows.append({
                "source": match.group(1),
                "source_id": match.group(2),
                "account_id": match.group(3),
                "doc_type": match.group(4),
                "occurred_at": match.group(5),
                "ingest_run": match.group(6),
                "turn_count": int(match.group(7)),
                "withheld_comment_count": int(match.group(8)),
            })
        if errors:
            raise ContractViolation("SourceIndexRow", errors)
        return rows

    def write_watermark(self, last_ingest_run: str, last_ingest_day: datetime.date | str,
                        rows: list[dict[str, Any]] | None = None) -> None:
        """Rewrite sources/_INDEX.md. rows=None keeps the rows already on disk."""
        day = last_ingest_day.isoformat() if isinstance(last_ingest_day, datetime.date) \
            else str(last_ingest_day)
        if not RUN_ID_RE.match(last_ingest_run):
            raise ContractViolation("StoreFrontmatter",
                                    ["last_ingest_run %r is not a run id" % last_ingest_run])
        if not WATERMARK_DAY_RE.match(day):
            raise ContractViolation("StoreFrontmatter",
                                    ["last_ingest_day %r is not a date" % day])
        existing = self.read_source_rows() if rows is None else [_source_row(r) for r in rows]
        self._write_sources_index(last_ingest_run, day, existing,
                                  run_id=last_ingest_run, last_verified=day)
        self._log(agent="store", action="write", stage="store", target="sources/_INDEX.md",
                  detail={"rows": len(existing), "watermark_day": 1})

    def record_sources(self, run_id: str, refs: list[dict[str, Any]]) -> int:
        """Append rows for what this ingest run took in. The watermark is moved separately."""
        current = {(r["source"], r["source_id"]): r for r in self.read_source_rows()}
        for ref in refs:
            row = _source_row(ref, run_id)
            current[(row["source"], row["source_id"])] = row
        merged = sorted(current.values(), key=lambda r: (r["occurred_at"], r["source_id"]))
        run, day = self.read_watermark()
        self._write_sources_index(run, day.isoformat() if day else None, merged,
                                  run_id=run_id, last_verified=run_id[:10])
        self._log(agent="store", action="write", stage="store", target="sources/_INDEX.md",
                  detail={"rows": len(merged), "added": len(refs)})
        return len(merged)

    def _write_sources_index(self, last_ingest_run: str | None, last_ingest_day: str | None,
                             rows: list[dict[str, Any]], run_id: str,
                             last_verified: str) -> Path:
        frontmatter = {
            "schema_version": schema_version("SourceDocument"),
            "owner": DEFAULT_OWNER,
            "source": "pipeline",
            "last_verified": last_verified,
            "run_id": run_id,
            "last_ingest_run": last_ingest_run,
            "last_ingest_day": last_ingest_day,
        }
        order = list(STORE_FRONTMATTER_KEYS) + ["last_ingest_run", "last_ingest_day"]
        text = _dump_frontmatter(frontmatter, order)
        text += "\n# Ingested sources\n\n" + SOURCE_INDEX_HEADER + "\n" + SOURCE_INDEX_SEPARATOR
        ordered = sorted(rows, key=lambda r: (r["occurred_at"], r["source_id"]))
        for row in ordered:
            text += "\n| %s | %s | %s | %s | %s | %s | %d | %d |" % (
                row["source"], row["source_id"], row["account_id"], row["doc_type"],
                row["occurred_at"], row["ingest_run"], int(row["turn_count"]),
                int(row["withheld_comment_count"]),
            )
        return self._write_text(self.sources_index_path, text + "\n")

    def write_source_document(self, doc: dict[str, Any]) -> Path:
        """Store the SCRUBBED source document the reader saw, so a citation can be expanded.

        There is deliberately no entry point here that stores unscrubbed text. A document
        whose `scrubbed` flag is not true is refused, not cleaned up.
        """
        validate(doc, "SourceDocument")
        if doc.get("scrubbed") is not True:
            raise ContractViolation(
                "SourceDocument",
                ["$.scrubbed: the store accepts scrubbed documents only; run the scrubber first"],
            )
        path = self.sources_dir / ("%s.json" % doc["source_id"])
        self._write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        self._log(agent="store", action="write", stage="store",
                  target="sources/%s.json" % doc["source_id"],
                  detail={"turns": len(doc.get("turns") or [])})
        return path

    # The brief names this one write_source_doc; the interface contract names it
    # write_source_document. Same function, so neither caller has to be wrong.
    write_source_doc = write_source_document

    def read_source_document(self, source_id: str) -> dict[str, Any]:
        path = self.sources_dir / ("%s.json" % source_id)
        if not path.is_file():
            raise ContractViolation("SourceDocument", ["no source document at %s" % path])
        doc = json.loads(path.read_text(encoding="utf-8"))
        self._log(agent="store", action="read", stage="store", target="sources/%s.json" % source_id)
        return doc

    # -------------------------------------------------------------- outputs

    def write_digest(self, week: str, md: str, html: str) -> tuple[Path, Path]:
        md_path = self._write_text(self.path / "digests" / ("%s.md" % week), md)
        html_path = self._write_text(self.path / "digests" / ("%s.html" % week), html)
        self._log(agent="store", action="write", stage="render", target="digests/%s" % week)
        return md_path, html_path

    def write_proposal(self, theme_id: str, week: str, run_id: str, title: str,
                       body: str, reason: str) -> Path:
        """One proposal file, status proposed. Filing is a human action, not this one."""
        if theme_id.startswith("NEW-"):
            raise ContractViolation("EditorProposal",
                                    ["placeholder %s reached the store; resolve it first" % theme_id])
        frontmatter = {
            "schema_version": schema_version("Theme"),
            "owner": DEFAULT_OWNER,
            "source": "synthesized",
            "last_verified": run_id[:10],
            "run_id": run_id,
            "theme_id": theme_id,
            "week": week,
            "status": "proposed",
            "filed_issue_url": None,
        }
        order = list(STORE_FRONTMATTER_KEYS) + ["theme_id", "week", "status", "filed_issue_url"]
        text = _dump_frontmatter(frontmatter, order)
        text += "\n# %s\n\n%s\n\n## Why it was proposed\n\n%s\n" % (
            _cell(title), body.strip("\n"), reason.strip("\n"))
        path = self._write_text(self.path / "proposals" / week / ("%s.md" % theme_id), text)
        self._log(agent="store", action="propose", stage="propose",
                  target="%s/%s" % (week, theme_id))
        return path

    def read_proposals(self, week: str) -> list[dict[str, Any]]:
        """Every proposal for a week: its frontmatter plus `path` and `body`."""
        directory = self.path / "proposals" / week
        out: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
            frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"))
            record = dict(frontmatter)
            record["path"] = str(path)
            record["body"] = body
            out.append(record)
        self._log(agent="store", action="read", stage="propose", target="proposals/%s" % week,
                  detail={"proposals": len(out)})
        return out

    def write_run_manifest(self, manifest: dict[str, Any]) -> Path:
        validate(manifest, "RunManifest")
        path = self.path / "runs" / manifest["run_id"] / "manifest.json"
        self._write_text(path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        self._log(agent="store", action="write", stage="store",
                  target="runs/%s/manifest.json" % manifest["run_id"])
        return path

    # -------------------------------------------------------------- git

    def is_readonly(self) -> tuple[bool, str | None]:
        if os.environ.get(READONLY_ENV) == "1":
            return True, "%s=1" % READONLY_ENV
        if not (self.path / ".git").exists():
            return True, "no .git directory at %s" % self.path
        return False, None

    def commit(self, message: str, run_id: str) -> str | None:
        """Stage everything and commit as the agent. None when the store is read only.

        Not an exception: the demo has to be green on a machine with no credential
        configured, so a skipped commit is one audit event with outcome withheld.
        """
        readonly, reason = self.is_readonly()
        if readonly:
            self._log(agent="store", action="commit", stage="store", target=str(self.path),
                      outcome="withheld", detail={"reason": reason})
            return None
        full = message if message.startswith("run %s: " % run_id) else "run %s: %s" % (run_id, message)
        self._git("add", "-A")
        staged = subprocess.run(["git", "-C", str(self.path), "diff", "--cached", "--quiet"],
                                capture_output=True, text=True)
        if staged.returncode == 0:
            self._log(agent="store", action="commit", stage="store", target=str(self.path),
                      outcome="withheld", detail={"reason": "nothing to commit"})
            return None
        self._git("-c", "user.name=%s" % COMMIT_AUTHOR_NAME,
                  "-c", "user.email=%s" % COMMIT_AUTHOR_EMAIL,
                  "commit", "--author=%s" % COMMIT_AUTHOR, "-m", full)
        sha = self._git("rev-parse", "HEAD").stdout.strip()
        self._log(agent="store", action="commit", stage="store", target=sha,
                  detail={"message_length": len(full)})
        if os.environ.get(PUSH_ENV) == "1":
            self._git("push")
            self._log(agent="store", action="write", stage="store", target="push",
                      detail={"commits": 1})
        return sha

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_NAME": COMMIT_AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": COMMIT_AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": COMMIT_AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": COMMIT_AUTHOR_EMAIL,
        })
        return subprocess.run(["git", "-C", str(self.path), *args],
                              check=True, capture_output=True, text=True, env=env)


def _theme_key_order() -> list[str]:
    from digest.contracts import load_schema

    return list(load_schema("Theme")["required"])


def _iso_week(day: str) -> tuple[int, int]:
    parsed = datetime.date.fromisoformat(day).isocalendar()
    return parsed[0], parsed[1]


def _source_row(ref: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    """Accept a plain index row or a SourceDocument and return one index row.

    The connector has a SourceDocument in hand and the ingest loop has a row; making the
    store take either saves every caller a translation step it would get subtly wrong.
    """
    meta = ref.get("meta") or {}
    row = {
        "source": ref["source"],
        "source_id": ref["source_id"],
        "account_id": ref["account_id"],
        "doc_type": ref["doc_type"],
        "occurred_at": ref["occurred_at"],
        "ingest_run": ref.get("ingest_run") or ref.get("ingest_run_id") or run_id,
        "turn_count": ref.get("turn_count",
                              meta.get("turn_count", len(ref.get("turns") or []))),
        "withheld_comment_count": ref.get("withheld_comment_count",
                                          meta.get("withheld_comment_count", 0)),
    }
    if not row["ingest_run"]:
        raise ContractViolation("SourceIndexRow", ["no ingest run id for %s" % row["source_id"]])
    return row
