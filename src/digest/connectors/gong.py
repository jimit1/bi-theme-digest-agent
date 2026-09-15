"""The Gong connector: three tool calls in, one SourceDocument out.

Two things here are deliberate and are the reason this is code and not a prompt.

The turn boundary is the monologue block Gong already gives us, and the per sentence
spans are kept on the turn rather than thrown away, so the verifier can resolve a
citation down to the sentence it came from instead of to a three minute block.

`start` and `end` are stored in the source system's own unit, milliseconds. The digest
renders seconds. Converting at the storage layer is how citations stop resolving.
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter
from typing import Any

from digest.connectors.base import (
    AccountDirectory,
    SourceRef,
    day_bounds,
    ingest_run_id_for,
)
from digest.connectors.mcp_client import McpToolClient
from digest.contracts import validate

__all__ = ["GongConnector"]

# parties[].affiliation. Unknown maps to momentive, not to client, so a speaker we
# cannot place can never produce a client claim.
_CLIENT_AFFILIATIONS = {"External"}


class GongConnector:
    name = "gong"

    def __init__(self, mcp_client: McpToolClient, accounts: AccountDirectory,
                 ingest_run_id: str | None = None) -> None:
        self._client = mcp_client
        self._accounts = accounts
        self._ingest_run_id = ingest_run_id

    # -- listing -----------------------------------------------------------
    def list_since(self, watermark: _dt.date | None, until: _dt.date) -> list[SourceRef]:
        if watermark is None:
            # From the beginning, which for a scoped server is the start of the only
            # window it will serve. Asking wider than that is a refusal, not a wider read.
            from_instant = self._client.window["from"]
        else:
            from_instant = day_bounds(watermark + _dt.timedelta(days=1))[0]
        to_instant = day_bounds(until)[1]
        refs: list[SourceRef] = []
        cursor: str | None = None
        while True:
            response = self._client.call(
                "gong_list_calls",
                {"from_date_time": from_instant, "to_date_time": to_instant, "cursor": cursor},
                schema="GongCallsResponse",
            )
            for call in response["calls"]:
                refs.append(SourceRef(
                    source="gong",
                    source_id=call["id"],
                    occurred_at=call["scheduled"] or call["started"],
                    doc_type="call",
                    title=call["title"],
                ))
            cursor = response["records"]["cursor"]
            if not cursor:
                break
        refs.sort(key=lambda r: (r["occurred_at"], r["source_id"]))
        return refs

    # -- fetching ----------------------------------------------------------
    def fetch(self, source_id: str) -> dict[str, Any]:
        extensive = self._client.call(
            "gong_get_calls_extensive", {"call_ids": [source_id]},
            schema="GongCallsExtensiveResponse",
        )
        transcripts = self._client.call(
            "gong_get_transcripts", {"call_ids": [source_id]},
            schema="GongTranscriptResponse",
        )
        call = _only(extensive["calls"], "call", source_id)
        transcript = _only(transcripts["callTranscripts"], "transcript", source_id)
        meta_data = call["metaData"]
        parties = call["parties"]
        by_speaker = {p["speakerId"]: p for p in parties if p.get("speakerId")}

        turns = [_turn(block, source_id, by_speaker) for block in transcript["transcript"]]
        account_id, account_name = self._resolve_account(parties)
        occurred_at = meta_data["scheduled"] or meta_data["started"]

        document = {
            "schema_version": "1.0.0",
            "source": "gong",
            "source_id": source_id,
            "title": meta_data["title"],
            "account_id": account_id,
            "account_name": account_name,
            "occurred_at": occurred_at,
            "doc_type": "call",
            "ingest_run_id": ingest_run_id_for(self._ingest_run_id, occurred_at),
            # The scrubber is a separate stage so its redaction count is its own number
            # in the audit log. It rewrites turns[].text and fills pii_counts in place.
            "scrubbed": True,
            "pii_counts": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0},
            "participants": [_participant(p) for p in parties],
            "turns": turns,
            "meta": {"withheld_comment_count": 0, "turn_count": len(turns), "soql": None},
        }
        validate(document, "SourceDocument")
        return document

    # -- account resolution ------------------------------------------------
    def _resolve_account(self, parties: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        """Match every External party's email domain against accounts.json.

        More than one account matching means the most matching parties wins, and a tie
        breaks on the lowest account id. No match at all leaves both fields null, and
        ingest counts that document as skipped rather than guessing.
        """
        hits: Counter[tuple[str, str]] = Counter()
        for party in parties:
            if party.get("affiliation") != "External":
                continue
            email = party.get("emailAddress") or ""
            if "@" not in email:
                continue
            resolved = self._accounts.by_domain(email)
            if resolved is not None:
                hits[resolved] += 1
        if not hits:
            return (None, None)
        best = min(hits.items(), key=lambda item: (-item[1], item[0][0]))[0]
        return best


def _only(rows: list[dict[str, Any]], what: str, source_id: str) -> dict[str, Any]:
    if not rows:
        from digest.errors import DigestError

        raise DigestError("mock Gong returned no %s for call %s" % (what, source_id))
    return rows[0]


def _side(affiliation: str | None) -> str:
    return "client" if affiliation in _CLIENT_AFFILIATIONS else "momentive"


def _participant(party: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": party["id"],
        "name": party["name"],
        "side": _side(party.get("affiliation")),
        "title": party.get("title"),
    }


def _turn(block: dict[str, Any], call_id: str,
          by_speaker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    speaker_id = block["speakerId"]
    party = by_speaker.get(speaker_id, {})
    affiliation = party.get("affiliation") or "Unknown"
    sentences = block["sentences"]
    spans = [{"start_ms": s["start"], "end_ms": s["end"], "text": s["text"]} for s in sentences]
    start_ms = spans[0]["start_ms"] if spans else 0
    end_ms = spans[-1]["end_ms"] if spans else 0
    return {
        "ref": {
            "call_id": call_id,
            "speaker_id": speaker_id,
            "speaker_name": party.get("name") or speaker_id,
            "affiliation": affiliation,
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
        "speaker_id": speaker_id,
        "speaker_side": _side(affiliation),
        "text": " ".join(s["text"] for s in sentences),
        "sentences": spans,
    }
