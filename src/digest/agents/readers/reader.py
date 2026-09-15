"""The two reader agents: one scrubbed source document in, one ReaderOutput out.

A reader is the narrowest role in the system. It sees exactly one SourceDocument, it has no
store, no tools, no account enrichment, and no memory of the document before it. That is why
extraction can run on the cheap tier and why a bad extraction can only ever spoil one
document.

The reader also fills none of the fields the pipeline owns. `claim_id`, `run_id`,
`account_id`, `speaker_side`, `prompt_hash` and the code owned half of `source_ref` are all
added later by `digest.verify.promote`, from the document rather than from the model. The
model fills the nine fields of `ReaderClaim` and nothing else, which is why `speaker_side`
is not something it can get wrong: the prompt tells it to quote client turns only, and the
verifier resolves the turn it actually cited and throws the claim away when that turn is a
Momentive Software employee.
"""
from __future__ import annotations

import functools
import hashlib
import pathlib
import re
from typing import Any

import yaml

from digest.errors import ContractViolation

__all__ = [
    "read_source",
    "prompt_for",
    "prompt_meta",
    "prompt_path",
    "prompt_hash_of",
    "render_user",
    "render_turns",
    "render_participants",
    "agent_for",
    "manifest",
    "SOURCES",
    "TIER",
    "SCHEMA_NAME",
    "STAGE",
]

PROMPT_DIR = pathlib.Path(__file__).resolve().parent

TIER = "extraction"
SCHEMA_NAME = "ReaderOutput"
STAGE = "extract"

SOURCES = ("gong", "salesforce")

_AGENTS = {"gong": "gong_reader", "salesforce": "sfdc_reader"}
_PROMPT_FILES = {"gong": "gong_reader.prompt.md", "salesforce": "sfdc_reader.prompt.md"}

# `---` alone on its own line. The file is frontmatter, system prompt, user template.
_SEPARATOR = re.compile(r"^---[ \t]*$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


def agent_for(source: str) -> str:
    """The audit agent name for a source. `gong_reader` or `sfdc_reader`."""
    try:
        return _AGENTS[source]
    except KeyError:
        raise ValueError(
            "unknown source %r, expected one of: %s" % (source, ", ".join(SOURCES))
        ) from None


def prompt_path(source: str) -> pathlib.Path:
    """Where the versioned prompt file for a source lives."""
    agent_for(source)
    return PROMPT_DIR / _PROMPT_FILES[source]


@functools.lru_cache(maxsize=None)
def _load_prompt(source: str) -> tuple[dict, str, str]:
    """Parse one prompt file into (frontmatter, system, user template).

    Parsed once per process. The file is the artefact under review in a pull request, so it
    is read from disk rather than held as a string literal in code.
    """
    path = prompt_path(source)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractViolation("ReaderPrompt", ["$: cannot read %s: %s" % (path, exc)]) from exc

    parts = _SEPARATOR.split(raw)
    # An opening `---` makes the first part empty: "", frontmatter, system, user.
    if len(parts) != 4 or parts[0].strip():
        raise ContractViolation(
            "ReaderPrompt",
            ["$: %s must be frontmatter, system prompt and user template, separated by "
             "three lines of exactly ---" % path],
        )
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ContractViolation("ReaderPrompt", ["$: %s frontmatter is not a mapping" % path])

    missing = [k for k in ("prompt_version", "schema", "tier") if k not in meta]
    if missing:
        raise ContractViolation(
            "ReaderPrompt",
            ["$.%s: missing from the frontmatter of %s" % (k, path) for k in missing],
        )
    if meta["schema"] != SCHEMA_NAME or meta["tier"] != TIER:
        raise ContractViolation(
            "ReaderPrompt",
            ["$: %s asks for schema %r tier %r, the reader role is schema %r tier %r"
             % (path, meta["schema"], meta["tier"], SCHEMA_NAME, TIER)],
        )
    return meta, parts[2].strip(), parts[3].strip()


def prompt_meta(source: str) -> dict:
    """The prompt file frontmatter: prompt_version, schema, tier, agent, source."""
    return dict(_load_prompt(source)[0])


def prompt_for(source: str) -> tuple[str, str]:
    """(system prompt, user template) for `gong` or `salesforce`."""
    _, system, template = _load_prompt(source)
    return system, template


def prompt_hash_of(source: str) -> str:
    """sha256 of the prompt file exactly as it sits on disk.

    Full digest, not truncated: this identifies the prompt artefact in a manifest, which is
    a different job from `Claim.prompt_hash`, which covers the rendered system and user text
    of one call and is the router's to compute.
    """
    return hashlib.sha256(prompt_path(source).read_bytes()).hexdigest()


# -- rendering -------------------------------------------------------------------


def render_participants(doc: dict) -> str:
    """One line per participant: name, side, title. Ids stay out; they would compete with
    the speaker ids in the turn headers and the model only ever needs one of them."""
    lines = []
    for person in doc["participants"]:
        title = person.get("title")
        suffix = ", %s" % title if title else ""
        lines.append("- %s (%s)%s" % (person["name"], person["side"], suffix))
    return "\n".join(lines)


def _gong_header(index: int, turn: dict) -> str:
    ref = turn["ref"]
    return "[turn %d | speaker_id %s | %s | %s | %d-%d]" % (
        index, ref["speaker_id"], ref["speaker_name"], turn["speaker_side"],
        ref["start_ms"], ref["end_ms"],
    )


def _gong_body(turn: dict) -> str:
    """The turn text with a `(start_ms-end_ms)` marker in front of each sentence.

    The markers let the model pick a contiguous span to quote. Strip every marker and the
    single space after it and what is left is `turn["text"]` character for character, which
    is the string the citation verifier will test the verbatim against.
    """
    sentences = turn["sentences"]
    if not sentences:
        return turn["text"]
    return " ".join(
        "(%d-%d) %s" % (s["start_ms"], s["end_ms"], s["text"]) for s in sentences
    )


def _salesforce_header(index: int, turn: dict) -> str:
    ref = turn["ref"]
    return "[turn %d | comment_id %s | %s | %s | %s]" % (
        index, ref["comment_id"], ref["author_name"], turn["speaker_side"],
        ref["created_at"],
    )


def render_turns(doc: dict) -> str:
    """The turns block of the user prompt, each turn headed by its own locator."""
    gong = doc["source"] == "gong"
    blocks = []
    for index, turn in enumerate(doc["turns"], start=1):
        header = _gong_header(index, turn) if gong else _salesforce_header(index, turn)
        body = _gong_body(turn) if gong else turn["text"]
        blocks.append("%s\n%s" % (header, body))
    if not blocks:
        return "(this document has no turns)"
    return "\n\n".join(blocks)


def render_user(doc: dict) -> str:
    """Fill the user template from one SourceDocument."""
    _, template = prompt_for(doc["source"])
    values = {
        "source": doc["source"],
        "source_id": doc["source_id"],
        "title": doc["title"] or "(none)",
        "account_name": doc["account_name"] or "(unresolved)",
        "doc_type": doc["doc_type"],
        "occurred_at": doc["occurred_at"],
        "participants": render_participants(doc),
        "turns": render_turns(doc),
    }

    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise ContractViolation(
                "ReaderPrompt",
                ["$: %s uses placeholder {{%s}}, which the renderer does not fill"
                 % (prompt_path(doc["source"]), name)],
            )
        return str(values[name])

    return _PLACEHOLDER.sub(substitute, template)


# -- the one entry point ---------------------------------------------------------


def read_source(doc: dict, router: Any, audit: Any) -> dict:
    """Extract the client claims from ONE scrubbed source document.

    Asks for tier `extraction` and schema `ReaderOutput`, logs one `read` event for the
    document, and lets the router log the model events. Returns the ReaderOutput the router
    validated, untouched. A `SchemaRejected` from the router is left to the caller in
    `digest.pipeline`, which records it as a rejected claim rather than retrying here.
    """
    source = doc["source"]
    agent = agent_for(source)
    system, _ = prompt_for(source)
    user = render_user(doc)

    run_id = getattr(audit, "run_id", None) or doc["ingest_run_id"]
    audit.log(
        agent=agent,
        action="read",
        stage=STAGE,
        target=doc["source_id"],
        detail={
            "source": source,
            "doc_type": doc["doc_type"],
            "turn_count": doc["meta"]["turn_count"],
            "scrubbed": doc["scrubbed"],
            "prompt_version": prompt_meta(source)["prompt_version"],
        },
    )

    result = router.complete(
        tier=TIER,
        system=system,
        user=user,
        schema_name=SCHEMA_NAME,
        run_id=run_id,
        agent=agent,
        audit=audit,
    )
    return result["data"]


def manifest() -> dict:
    """What this package is, for the build manifest: both prompts, their versions and hashes."""
    return {
        "agents": [
            {
                "agent": agent_for(source),
                "source": source,
                "tier": TIER,
                "schema": SCHEMA_NAME,
                "prompt_file": prompt_path(source).name,
                "prompt_version": prompt_meta(source)["prompt_version"],
                "prompt_sha256": prompt_hash_of(source),
            }
            for source in SOURCES
        ]
    }
