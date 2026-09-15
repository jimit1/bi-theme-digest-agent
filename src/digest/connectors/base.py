"""The connector seam: what a source looks like to the pipeline, and nothing else.

A new source is one file implementing `SourceConnector` plus a config entry. The pipeline
does not learn a new shape and does not grow a branch, which is the whole reason the
interface is this small.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

from digest.errors import DigestError

__all__ = [
    "SourceRef",
    "SourceConnector",
    "AccountDirectory",
    "parse_instant",
    "format_instant",
    "day_bounds",
    "ingest_run_id_for",
]

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")


class SourceRef(TypedDict):
    source: Literal["gong", "salesforce"]
    source_id: str
    occurred_at: str
    doc_type: Literal["call", "case"]
    title: str


@runtime_checkable
class SourceConnector(Protocol):
    name: str

    def list_since(self, watermark: _dt.date | None,
                   until: _dt.date) -> list[SourceRef]: ...

    def fetch(self, source_id: str) -> dict: ...


# ---------------------------------------------------------------------------
# Time helpers. Kept here rather than in each connector so the two agree on what
# "inclusive" means at both ends of a day.
# ---------------------------------------------------------------------------

def parse_instant(raw: str, *, end_of_day: bool = False) -> _dt.datetime:
    text = (raw or "").strip()
    if not text:
        raise DigestError("empty timestamp")
    if _DATE_ONLY.match(text):
        text = text + ("T23:59:59Z" if end_of_day else "T00:00:00Z")
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DigestError("not an ISO 8601 timestamp: %s" % raw) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def format_instant(value: _dt.datetime) -> str:
    return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def day_bounds(day: _dt.date) -> tuple[str, str]:
    """The first and last instant of a day, both inclusive."""
    return ("%sT00:00:00Z" % day.isoformat(), "%sT23:59:59Z" % day.isoformat())


def ingest_run_id_for(explicit: str | None, occurred_at: str) -> str:
    """The run id stamped on a fetched document.

    `SourceConnector` takes no run id, so it comes from `DIGEST_RUN_ID` when the pipeline
    sets it. Failing that it falls back to the pinned 06:00Z ingest slot of the day the
    document happened on, which keeps a standalone fetch reproducible instead of stamping
    it with wall clock time.
    """
    for candidate in (explicit, os.environ.get("DIGEST_RUN_ID")):
        if candidate and _RUN_ID.match(candidate.strip()):
            return candidate.strip()
    return parse_instant(occurred_at).strftime("%Y-%m-%dT06:00Z")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountDirectory:
    """Resolves an email domain or a Salesforce AccountId to an ACC-nnnn id.

    Reads `accounts.json` directly rather than through a tool, because `domain` is not a
    Salesforce field: it sits beside the Account record, not inside it, so that the mock
    can still claim to mirror the API field for field. In production this lookup is a CRM
    call and the connector interface does not change.
    """

    def __init__(self, accounts: list[dict[str, Any]]) -> None:
        self._by_domain: dict[str, tuple[str, str]] = {}
        self._by_sfdc_id: dict[str, tuple[str, str]] = {}
        for account in accounts:
            account_id = account["account_id"]
            name = account["record"]["Name"]
            domain = (account.get("domain") or "").strip().lower()
            if domain:
                self._by_domain[domain] = (account_id, name)
            self._by_sfdc_id[account["record"]["Id"]] = (account_id, name)

    @classmethod
    def from_file(cls, path: str | pathlib.Path) -> "AccountDirectory":
        location = pathlib.Path(path)
        if location.is_dir():
            location = location / "accounts.json"
        if not location.is_file():
            raise DigestError("accounts file not found: %s" % location)
        with location.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        from digest.contracts import validate

        validate(document, "MockAccountsFile")
        return cls(document["accounts"])

    @classmethod
    def from_mock_dir(cls, mock_dir: str | pathlib.Path | None = None) -> "AccountDirectory":
        base = mock_dir or os.environ.get("DIGEST_MOCK_DIR") or "data/mock"
        return cls.from_file(pathlib.Path(base) / "accounts.json")

    def by_domain(self, email_or_domain: str) -> tuple[str, str] | None:
        text = (email_or_domain or "").strip().lower()
        if "@" in text:
            text = text.rsplit("@", 1)[-1]
        return self._by_domain.get(text)

    def by_sfdc_id(self, sfdc_account_id: str) -> tuple[str, str] | None:
        return self._by_sfdc_id.get((sfdc_account_id or "").strip())
