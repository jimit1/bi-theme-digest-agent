"""Schema validation and citation verification for the reader pipeline.

Everything here is deterministic. No model call happens in this module.

Flow: a reader agent returns a `ReaderOutput` for exactly one `SourceDocument`.
`validate_reader_output` checks the envelope against the contract. `verify_citations`
walks every `ReaderClaim` inside it, resolves each one against the turns of the source
document, and either finalizes it into a full `Claim` (via `finalize_claim`) or produces
a `RejectedClaim`. Rejection is data, never an exception: a run with rejections is a
normal run (see contracts/errors.md).

The one place strictness matters most: a citation resolves against the SCRUBBED turn
text, and only against the exact sentences the cited span covers. A verbatim that is a
substring of the whole turn but not of the cited span is still rejected. That is the
traceability guarantee this module exists to enforce.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from digest.contracts import iter_errors, validate
from digest.errors import CitationUnresolved

__all__ = [
    "validate_reader_output",
    "compute_claim_id",
    "verify_citations",
    "finalize_claim",
    "resolve_citation",
    "citation_label",
]

_DEFAULT_PROMPT_HASH = "0" * 16


# ---------------------------------------------------------------------------
# claim_id, pinned in contracts/file_formats.md section 1
# ---------------------------------------------------------------------------

def compute_claim_id(source_ref: dict[str, Any], verbatim: str) -> str:
    """sha256(canonical_json(source_ref) + verbatim), first 12 hex chars.

    Reference implementation and test vector: contracts/file_formats.md section 1 and
    contracts/examples/Claim.example.json.
    """
    digest = hashlib.sha256()
    digest.update(
        json.dumps(source_ref, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    )
    digest.update(verbatim.encode("utf-8"))
    return digest.hexdigest()[:12]


# ---------------------------------------------------------------------------
# validate_reader_output
# ---------------------------------------------------------------------------

def validate_reader_output(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw reader agent response against ReaderOutput.schema.json.

    Raises ContractViolation on failure. Returns the same object on success; this
    module never mutates what it is handed.
    """
    validate(raw, "ReaderOutput")
    return raw


# ---------------------------------------------------------------------------
# Turn resolution, shared by verify_citations, finalize_claim and resolve_citation
# ---------------------------------------------------------------------------

def _match_gong_turn(ref: dict[str, Any], source_doc: dict[str, Any]) -> dict[str, Any] | None:
    """The turn whose speaker and time range contain this citation.

    Matching is by speaker_id first, then containment: the cited [start_ms, end_ms]
    must lie inside the turn's own [start_ms, end_ms], which is the monologue block's
    full extent (first sentence start to last sentence end). A citation that exactly
    equals a turn's own boundary trivially satisfies containment, so the common case
    of citing a whole turn works the same way as citing a narrower span inside it.
    """
    call_id = ref["call_id"]
    speaker_id = ref["speaker_id"]
    start_ms = ref["start_ms"]
    end_ms = ref["end_ms"]
    for turn in source_doc.get("turns", []):
        tref = turn.get("ref", {})
        if "call_id" not in tref:
            continue
        if tref.get("call_id") != call_id or turn.get("speaker_id") != speaker_id:
            continue
        if tref.get("start_ms", 0) <= start_ms and tref.get("end_ms", 0) >= end_ms:
            return turn
    return None


def _gong_span_text(turn: dict[str, Any], start_ms: int, end_ms: int) -> str:
    """Sentences whose [start_ms, end_ms] lie within the cited window, inclusive.

    Tolerance is zero: a sentence that starts or ends even one millisecond outside the
    cited window is excluded, never rounded in. Joined with a single ASCII space, the
    same joiner the connector used to build turns[].text from all of a turn's
    sentences (contracts/file_formats.md, digest.connectors.gong).
    """
    parts = [
        sentence["text"]
        for sentence in turn.get("sentences", [])
        if sentence["start_ms"] >= start_ms and sentence["end_ms"] <= end_ms
    ]
    return " ".join(parts)


def _match_sfdc_turn(ref: dict[str, Any], source_doc: dict[str, Any]) -> dict[str, Any] | None:
    case_id = ref["case_id"]
    comment_id = ref["comment_id"]
    for turn in source_doc.get("turns", []):
        tref = turn.get("ref", {})
        if "comment_id" not in tref:
            continue
        if tref.get("case_id") == case_id and tref.get("comment_id") == comment_id:
            return turn
    return None


def _resolve(source: str, ref: dict[str, Any],
             source_doc: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """(turn, resolved span text). turn is None when nothing matches; span text is
    "" in that case."""
    if source == "gong":
        turn = _match_gong_turn(ref, source_doc)
        if turn is None:
            return None, ""
        return turn, _gong_span_text(turn, ref["start_ms"], ref["end_ms"])
    turn = _match_sfdc_turn(ref, source_doc)
    if turn is None:
        return None, ""
    return turn, turn["text"]


def _what_was_tried(source: str, ref: dict[str, Any]) -> str:
    if source == "gong":
        return "gong turn for speaker_id=%s call_id=%s span=[%d, %d]" % (
            ref["speaker_id"], ref["call_id"], ref["start_ms"], ref["end_ms"]
        )
    return "salesforce comment_id=%s in case_id=%s" % (ref["comment_id"], ref["case_id"])


# ---------------------------------------------------------------------------
# resolve_citation / citation_label
# ---------------------------------------------------------------------------

def resolve_citation(claim: dict[str, Any], source_doc: dict[str, Any]) -> str:
    """The resolved source text a Claim's source_ref points at.

    Reused by the independent citation audit and the HTML renderer so there is exactly
    one place that knows how a claim expands back to its source moment. Raises
    CitationUnresolved if the claim's own source_ref no longer resolves against
    source_doc, which should not happen for a Claim this module produced itself.
    """
    ref = claim["source_ref"]
    source = claim["source"]
    turn, span_text = _resolve(source, ref, source_doc)
    if turn is None:
        raise CitationUnresolved(
            claim.get("claim_id", ""), source_doc.get("source_id", ""),
            "no turn resolves for %s" % _what_was_tried(source, ref),
        )
    return span_text


def _mmss(start_ms: int) -> str:
    total_seconds = start_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return "%02d:%02d" % (minutes, seconds)


def citation_label(claim: dict[str, Any]) -> str:
    """'call <id> at mm:ss' for Gong, 'case <number> comment <id>' for Salesforce."""
    ref = claim["source_ref"]
    if claim["source"] == "gong":
        return "call %s at %s" % (ref["call_id"], _mmss(ref["start_ms"]))
    return "case %s comment %s" % (ref["case_number"], ref["comment_id"])


# ---------------------------------------------------------------------------
# finalize_claim
# ---------------------------------------------------------------------------

def _captured_at(now: _dt.datetime | None = None) -> str:
    moment = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def finalize_claim(reader_claim: dict[str, Any], source_doc: dict[str, Any], run_id: str,
                    account: dict[str, Any], prompt_hash: str, model_tier: str) -> dict[str, Any]:
    """Fill every code-owned field of a Claim and validate the result.

    The model fills exactly the nine ReaderClaim fields. Everything else here is
    filled by code: the full source_ref (Gong speaker_name and affiliation, or
    Salesforce case_number, author_id, author_name and created_at, copied from the
    matching SourceDocument turn, never invented), account_id/account_name/account_type
    from `account`, speaker_side derived from that same turn, claim_id per the pinned
    rule in contracts/file_formats.md section 1, run_id, captured_at, prompt_hash and
    model_tier.

    Raises CitationUnresolved if the reader claim's locator does not resolve to a turn
    in source_doc, and ContractViolation if the assembled document still fails
    Claim.schema.json.
    """
    source = reader_claim["source"]
    ref = reader_claim["source_ref"]
    turn, _span_text = _resolve(source, ref, source_doc)
    if turn is None:
        raise CitationUnresolved(
            "", source_doc.get("source_id", ""),
            "no turn resolves for %s" % _what_was_tried(source, ref),
        )
    tref = turn["ref"]

    if source == "gong":
        full_ref = {
            "call_id": ref["call_id"],
            "speaker_id": ref["speaker_id"],
            "speaker_name": tref["speaker_name"],
            "affiliation": tref["affiliation"],
            "start_ms": ref["start_ms"],
            "end_ms": ref["end_ms"],
        }
    else:
        full_ref = {
            "case_id": ref["case_id"],
            "case_number": tref["case_number"],
            "comment_id": ref["comment_id"],
            "author_id": tref["author_id"],
            "author_name": tref["author_name"],
            "created_at": tref["created_at"],
        }

    verbatim = reader_claim["verbatim"]
    claim = {
        "schema_version": "1.0.0",
        "claim_id": compute_claim_id(full_ref, verbatim),
        "run_id": run_id,
        "source": source,
        "source_ref": full_ref,
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "account_type": account["account_type"],
        "speaker_side": turn["speaker_side"],
        "verbatim": verbatim,
        "paraphrase": reader_claim["paraphrase"],
        "topic": reader_claim["topic"],
        "product_area": reader_claim["product_area"],
        "claim_type": reader_claim["claim_type"],
        "importance": reader_claim["importance"],
        "importance_reason": reader_claim["importance_reason"],
        "captured_at": _captured_at(),
        "prompt_hash": prompt_hash,
        "model_tier": model_tier,
    }
    validate(claim, "Claim")
    return claim


# ---------------------------------------------------------------------------
# verify_citations
# ---------------------------------------------------------------------------

def _claim_schema_errors(source: str, source_id: str, reader_claim: dict[str, Any]) -> list[str]:
    """Validate one ReaderClaim in isolation by wrapping it in a minimal ReaderOutput.

    contracts/ has no standalone ReaderClaim schema file (every schema is self
    contained, per contracts/README.md), so a single claim is checked by embedding it
    in an otherwise trivially valid envelope and reusing the ReaderOutput validator.
    This lets one malformed claim in a batch fail on its own instead of invalidating
    every sibling claim in the same reader output.
    """
    wrapper = {
        "schema_version": "1.0.0",
        "source": source,
        "source_id": source_id,
        "claims": [reader_claim],
        "no_claims_reason": None,
    }
    return iter_errors(wrapper, "ReaderOutput")


def _rejected(run_id: str, source: str, source_id: str, reason_code: str, reason: str,
              raw_claim: dict[str, Any]) -> dict[str, Any]:
    doc = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "source": source,
        "source_id": source_id,
        "reason_code": reason_code,
        "reason": reason[:500],
        "raw": dict(raw_claim),
    }
    validate(doc, "RejectedClaim")
    return doc


def verify_citations(reader_output: dict[str, Any], source_doc: dict[str, Any], run_id: str,
                      account: dict[str, Any], *, prompt_hash: str = _DEFAULT_PROMPT_HASH,
                      model_tier: str = "extraction",
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Verify every claim in one reader output against its source document.

    Returns (accepted, rejected): accepted are Claim.schema.json documents, rejected
    are RejectedClaim.schema.json documents carrying the post-scrub reader claim as
    `raw`. Never mutates `reader_output` or any claim inside it. Never raises for a bad
    claim; a run with rejections is a normal run.

    prompt_hash and model_tier are keyword only with deterministic defaults because the
    brief's pinned signature does not carry them, but every accepted Claim must carry
    real values (Claim.schema.json requires both) to be finalized. A caller that has the
    real prompt_hash and model_tier for this reader call should pass them explicitly.

    The checks run in this pinned order, so reason_code is deterministic for the same
    input: schema_invalid, citation_unresolved (no turn resolves), speaker_not_client,
    citation_unresolved (verbatim not a substring of the resolved span), duplicate.
    """
    source = reader_output["source"]
    source_id = reader_output["source_id"]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_claim_ids: set[str] = set()

    for reader_claim in reader_output.get("claims", []):
        schema_errors = _claim_schema_errors(source, source_id, reader_claim)
        if schema_errors:
            rejected.append(_rejected(
                run_id, source, source_id, "schema_invalid",
                "claim failed ReaderClaim shape: %s" % "; ".join(schema_errors),
                reader_claim,
            ))
            continue

        claim_source = reader_claim["source"]
        ref = reader_claim["source_ref"]
        verbatim = reader_claim["verbatim"]
        turn, span_text = _resolve(claim_source, ref, source_doc)

        if turn is None:
            rejected.append(_rejected(
                run_id, source, source_id, "citation_unresolved",
                "turn not found: tried %s; verbatim[:40]=%r"
                % (_what_was_tried(claim_source, ref), verbatim[:40]),
                reader_claim,
            ))
            continue

        if turn["speaker_side"] != "client":
            rejected.append(_rejected(
                run_id, source, source_id, "speaker_not_client",
                "resolved turn for %s has speaker_side=%s, not client"
                % (_what_was_tried(claim_source, ref), turn["speaker_side"]),
                reader_claim,
            ))
            continue

        if verbatim not in span_text:
            rejected.append(_rejected(
                run_id, source, source_id, "citation_unresolved",
                "turn found (%s); resolved span text length=%d; verbatim[:40]=%r "
                "is not a substring of the resolved span"
                % (_what_was_tried(claim_source, ref), len(span_text), verbatim[:40]),
                reader_claim,
            ))
            continue

        claim = finalize_claim(reader_claim, source_doc, run_id, account, prompt_hash, model_tier)

        if claim["claim_id"] in seen_claim_ids:
            rejected.append(_rejected(
                run_id, source, source_id, "duplicate",
                "claim_id %s already appeared in source %s" % (claim["claim_id"], source_id),
                reader_claim,
            ))
            continue

        seen_claim_ids.add(claim["claim_id"])
        accepted.append(claim)

    return accepted, rejected
