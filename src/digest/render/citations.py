"""Citation labels and the source moment a citation expands to.

`digest.verify` (task B13's sibling, being written in parallel) is documented in
`contracts/INTERFACES.md` to own a `citation_label` helper, but the module does not exist
yet in this checkout. This file reimplements the same label locally rather than importing a
module that is not there. The format is pinned by `contracts/file_formats.md` section 5,
the "moment" column of a theme's evidence table:

    call 7782934451002 at 06:58, Dana Ruiz          (Gong)
    case 00001042 comment 00a8W00000XfT2mQAF        (Salesforce)

`digest.store.source_ref_label` already produces the first half of the Gong form (without
the speaker name) and the whole of the Salesforce form; it is reused here rather than
duplicated, per the lowest-diff rule. Whoever writes `digest.verify.citation_label` should
match this output exactly, since it is the contract-documented format, not an invention of
this module.
"""
from __future__ import annotations

from typing import Any

from digest.errors import ContractViolation
from digest.store import Store, source_ref_label

__all__ = ["citation_label", "source_moment"]


def citation_label(claim: dict[str, Any]) -> str:
    """`call <id> at mm:ss, <speaker>` or `case <number> comment <id>`."""
    ref = claim.get("source_ref") or {}
    label = source_ref_label(claim)
    if claim.get("source") == "gong":
        speaker = ref.get("speaker_name")
        if speaker:
            label = "%s, %s" % (label, speaker)
    return label


def _find_turn(turns: list[dict[str, Any]], ref: dict[str, Any], source: str) -> tuple[int, dict[str, Any]] | None:
    for index, turn in enumerate(turns):
        turn_ref = turn.get("ref") or {}
        if source == "gong":
            if (
                turn_ref.get("call_id") == ref.get("call_id")
                and turn_ref.get("speaker_id") == ref.get("speaker_id")
                and turn_ref.get("start_ms") == ref.get("start_ms")
                and turn_ref.get("end_ms") == ref.get("end_ms")
            ):
                return index, turn
        else:
            if turn_ref.get("comment_id") == ref.get("comment_id"):
                return index, turn
    return None


def _sentence_context(turns: list[dict[str, Any]], turn_index: int, verbatim: str) -> tuple[str | None, str | None]:
    """The sentence immediately before and after the one(s) containing `verbatim`.

    Crosses into the previous or next turn when the verbatim sits at the edge of its own
    turn's sentence list, per contracts/INTERFACES.md under digest.render.
    """
    sentences = turns[turn_index].get("sentences") or []
    if not sentences:
        return None, None
    joined_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for sentence in sentences:
        text = sentence.get("text", "")
        if joined_parts:
            pos += 1  # the single ASCII space the turn text was joined with
        start = pos
        joined_parts.append(text)
        pos += len(text)
        spans.append((start, pos))
    joined = " ".join(joined_parts)
    start_char = joined.find(verbatim)
    if start_char == -1:
        return None, None
    end_char = start_char + len(verbatim)

    first_idx = None
    last_idx = None
    for idx, (s, e) in enumerate(spans):
        if first_idx is None and e > start_char:
            first_idx = idx
        if s < end_char:
            last_idx = idx
    if first_idx is None:
        first_idx = 0
    if last_idx is None:
        last_idx = len(spans) - 1

    if first_idx > 0:
        before = sentences[first_idx - 1].get("text")
    elif turn_index > 0:
        prev_sentences = turns[turn_index - 1].get("sentences") or []
        before = prev_sentences[-1].get("text") if prev_sentences else None
    else:
        before = None

    if last_idx < len(sentences) - 1:
        after = sentences[last_idx + 1].get("text")
    elif turn_index < len(turns) - 1:
        next_sentences = turns[turn_index + 1].get("sentences") or []
        after = next_sentences[0].get("text") if next_sentences else None
    else:
        after = None

    return before, after


def source_moment(claim: dict[str, Any], store: Store) -> dict[str, Any]:
    """What the HTML expands a claim's citation into.

    Reads `sources/<source_id>.json` from the store. When the document is missing, the
    verbatim is still returned but `available` is False and `before`/`after` are None, so
    the caller renders "context unavailable" instead of raising.
    """
    ref = claim["source_ref"]
    source = claim["source"]
    verbatim = claim["verbatim"]
    if source == "gong":
        source_id = ref["call_id"]
    else:
        source_id = ref["case_id"]

    try:
        doc = store.read_source_document(source_id)
    except ContractViolation:
        return {
            "source": source,
            "label": citation_label(claim),
            "speaker": ref.get("speaker_name") if source == "gong" else ref.get("author_name"),
            "verbatim": verbatim,
            "before": None,
            "after": None,
            "turn_text": None,
            "occurred_at": None,
            "meta": dict(ref),
            "available": False,
        }

    turns = doc.get("turns") or []
    found = _find_turn(turns, ref, source)
    before: str | None = None
    after: str | None = None
    turn_text: str | None = None
    if found is not None:
        turn_index, turn = found
        turn_text = turn.get("text")
        if source == "gong":
            before, after = _sentence_context(turns, turn_index, verbatim)

    if source == "gong":
        label = citation_label(claim)
        speaker = ref.get("speaker_name")
        meta = {"call_id": ref.get("call_id"), "start_ms": ref.get("start_ms"), "end_ms": ref.get("end_ms")}
    else:
        label = citation_label(claim)
        speaker = ref.get("author_name")
        meta = {"case_number": ref.get("case_number"), "comment_id": ref.get("comment_id")}

    return {
        "source": source,
        "label": label,
        "speaker": speaker,
        "verbatim": verbatim,
        "before": before,
        "after": after,
        "turn_text": turn_text,
        "occurred_at": doc.get("occurred_at"),
        "meta": meta,
        "available": found is not None,
    }
