"""Deterministic PII scrubber. No model call, ever.

Contract: contracts/INTERFACES.md, section `digest.pii.scrubber`, plus
`contracts/PiiNames.schema.json` for the names file shape.

`scrub` runs four passes in a fixed order, EMAIL, PHONE, ADDRESS, NAME, so a name that
happens to sit inside an already redacted email or address is gone before the name pass
ever sees it. Every pass is a plain regex substitution: nothing here calls a model, because
a join, a regex, or arithmetic is exactly what deterministic code is for (COMMON_RULES #8).

`load_names` accepts everything the contract's `path: str | Path | None` signature promises,
and additionally accepts a list of paths so the caller can union the generated corpus names
file with a hand written traps file. Passing None keeps the contract's documented default,
`data/mock/pii_names.json`, and additionally folds in `data/mock/traps/pii_names.json` when
it exists, because a name registered in either file must be caught and over redaction is the
safe direction here (INTERFACES.md, digest.pii.scrubber rules).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Iterable

PLACEHOLDERS = ("[EMAIL]", "[PHONE]", "[ADDRESS]", "[NAME]")

_DEFAULT_NAMES_PATH = Path("data/mock/pii_names.json")
_DEFAULT_TRAPS_NAMES_PATH = Path("data/mock/traps/pii_names.json")

_EMPTY_COUNTS = {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}

# --- EMAIL ------------------------------------------------------------------
# any local@domain.tld, RFC-ish rather than fully RFC 5322: this is a mock corpus, not a
# mail server, so the common local-part and domain character classes are enough.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# --- PHONE --------------------------------------------------------------
# (612) 555-0147 / 612-555-0147 / 612.555.0147 / +1 612 555 0147 / 6125550147.
# The lookaround digit guards keep a 10 digit phone number from ever matching as a
# substring of a longer run of digits (a Salesforce id, a case number, an amount), and the
# fixed 3-3-4 grouping with a repeated separator keeps it from matching a date (2-2-4) or an
# ISO timestamp or an mm:ss offset, none of which share that grouping.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:"
    r"\(\d{3}\)[ ]?\d{3}[-.]\d{4}"
    r"|\+1[ .-]?\d{3}[ .-]?\d{3}[ .-]?\d{4}"
    r"|\d{3}[-.]\d{3}[-.]\d{4}"
    r"|\d{10}"
    r")(?!\d)"
)

# --- ADDRESS ------------------------------------------------------------
# <number> <1-4 words> <street suffix>, optionally followed by ", City, ST 12345".
_STREET_SUFFIX = (
    r"(?:Lane|Ln|Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|"
    r"Way|Court|Ct|Place|Pl)"
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z]+\s+){1,4}" + _STREET_SUFFIX + r"\b\.?"
    r"(?:,\s*[A-Za-z][A-Za-z .]*,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?)?",
    re.IGNORECASE,
)

_NEVER_MATCHES = re.compile(r"(?!x)x")


def load_names(path: "str | Path | list | None" = None) -> list[str]:
    """Load and union the person names the scrubber must redact.

    `path` may be a single path (str or Path), a list of paths, or None. None is the
    contract's documented default plus the optional traps file: `data/mock/pii_names.json`
    and, if it exists, `data/mock/traps/pii_names.json`. Missing files in the list are
    skipped rather than raising, since the traps file is optional. Names are deduplicated
    case-insensitively, first occurrence wins the exact casing kept.
    """
    if path is None:
        candidates: list[Path] = [_DEFAULT_NAMES_PATH, _DEFAULT_TRAPS_NAMES_PATH]
    elif isinstance(path, (list, tuple)):
        candidates = [Path(p) for p in path]
    else:
        candidates = [Path(path)]

    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.exists():
            continue
        with candidate.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        for name in data.get("names", []):
            key = name.strip()
            if key and key.lower() not in seen:
                seen.add(key.lower())
                names.append(key)
    return names


def _name_patterns(name: str) -> list[str]:
    parts = name.split()
    if not parts:
        return []
    full = r"\s+".join(re.escape(p) for p in parts)
    patterns = [rf"\b{full}\b"]
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        patterns.append(rf"\b{re.escape(last)}\s*,\s*{re.escape(first)}\b")
        if "-" in last:
            patterns.append(rf"\b{re.escape(last)}\b")
    return patterns


def _build_name_regex(names: Iterable[str]) -> re.Pattern:
    patterns: list[str] = []
    seen: set[str] = set()
    for name in names:
        for pattern in _name_patterns(name):
            if pattern not in seen:
                seen.add(pattern)
                patterns.append(pattern)
    if not patterns:
        return _NEVER_MATCHES
    # Longest alternative first: with same start position a full "First Last" match should
    # win over a bare surname alternative from a different name entry.
    patterns.sort(key=len, reverse=True)
    return re.compile("|".join(patterns), re.IGNORECASE)


def scrub(text: str, names: "list[str] | None" = None) -> tuple[str, dict]:
    """Redact one string. Returns (clean_text, counts). Idempotent: scrubbing already
    scrubbed text returns it unchanged with all-zero counts, because none of the patterns
    below can match a placeholder token."""
    if names is None:
        names = load_names()

    counts = dict(_EMPTY_COUNTS)

    text, n = _EMAIL_RE.subn("[EMAIL]", text)
    counts["EMAIL"] += n

    text, n = _PHONE_RE.subn("[PHONE]", text)
    counts["PHONE"] += n

    text, n = _ADDRESS_RE.subn("[ADDRESS]", text)
    counts["ADDRESS"] += n

    if names:
        name_re = _build_name_regex(names)
        text, n = name_re.subn("[NAME]", text)
        counts["NAME"] += n

    return text, counts


def _scrub_field(doc: dict, field: str, names: "list[str] | None", total: dict) -> None:
    value = doc.get(field)
    if value:
        clean, counts = scrub(value, names)
        doc[field] = clean
        for key in total:
            total[key] += counts[key]


def scrub_document(doc: dict, names: "list[str] | None" = None) -> tuple[dict, dict]:
    """Redact a SourceDocument in place (on a copy): every `turns[].text`, every
    `turns[].sentences[].text` when present, and the document's title (Salesforce calls it
    `Case.Subject` before it lands in this dict, so a `subject` field is scrubbed too if a
    caller ever sets one). Ids and participants are never touched. Returns (doc, counts)
    with counts summed across every turn."""
    if names is None:
        names = load_names()

    doc = copy.deepcopy(doc)
    total = dict(_EMPTY_COUNTS)

    for turn in doc.get("turns", None) or []:
        text = turn.get("text", "")
        if text:
            clean, counts = scrub(text, names)
            turn["text"] = clean
            for key in total:
                total[key] += counts[key]
        for sentence in turn.get("sentences", None) or []:
            s_text = sentence.get("text", "")
            if s_text:
                clean, counts = scrub(s_text, names)
                sentence["text"] = clean
                for key in total:
                    total[key] += counts[key]

    _scrub_field(doc, "title", names, total)
    _scrub_field(doc, "subject", names, total)

    return doc, total
