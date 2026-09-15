"""The Salesforce connector: cases in, one SourceDocument out, private comments absent.

The withheld count is carried through from the tool response into the document, because
a control you cannot see fire is not a control. The number is what the audit log writes.

`CaseComment.CreatedById` does not say whether an author is staff or a customer, so the
connector asks `sfdc_get_users` and reads `UserType`. Standard is a Momentive Software
employee, every other value is a portal or community user, and an id that does not
resolve maps to momentive, because the safe default is that an unidentified speaker is
not a client.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from digest.connectors.base import (
    AccountDirectory,
    SourceRef,
    day_bounds,
    ingest_run_id_for,
)
from digest.connectors.mcp_client import McpToolClient
from digest.contracts import validate

__all__ = ["SalesforceConnector"]

_STAFF_USER_TYPE = "Standard"


class SalesforceConnector:
    name = "salesforce"

    def __init__(self, mcp_client: McpToolClient, accounts: AccountDirectory,
                 ingest_run_id: str | None = None) -> None:
        self._client = mcp_client
        self._accounts = accounts
        self._ingest_run_id = ingest_run_id

    # -- listing -----------------------------------------------------------
    def list_since(self, watermark: _dt.date | None, until: _dt.date) -> list[SourceRef]:
        if watermark is None:
            created_from = self._client.window["from"]
        else:
            created_from = day_bounds(watermark + _dt.timedelta(days=1))[0]
        created_to = day_bounds(until)[1]
        response = self._client.call(
            "sfdc_query_cases",
            {"created_from": created_from, "created_to": created_to},
            schema="SalesforceQueryResponse",
        )
        refs = [
            SourceRef(source="salesforce", source_id=row["Id"],
                      occurred_at=row["CreatedDate"], doc_type="case",
                      title=row["Subject"])
            for row in response["records"]
        ]
        refs.sort(key=lambda r: (r["occurred_at"], r["source_id"]))
        return refs

    # -- fetching ----------------------------------------------------------
    def fetch(self, source_id: str) -> dict[str, Any]:
        response = self._client.call(
            "sfdc_get_case", {"case_id": source_id}, schema="SalesforceCaseResponse",
        )
        case = response["case"]
        comments = sorted(response["comments"], key=lambda c: (c["CreatedDate"], c["Id"]))
        users = self._users([c["CreatedById"] for c in comments])

        turns = [_turn(case, comment, users) for comment in comments]
        resolved = self._accounts.by_sfdc_id(case["AccountId"])
        account_id, account_name = resolved if resolved else (None, None)
        occurred_at = case["CreatedDate"]

        document = {
            "schema_version": "1.0.0",
            "source": "salesforce",
            "source_id": source_id,
            # Metadata for the renderer, not a turn. No claim may cite it.
            "title": case["Subject"],
            "account_id": account_id,
            "account_name": account_name,
            "occurred_at": occurred_at,
            "doc_type": "case",
            "ingest_run_id": ingest_run_id_for(self._ingest_run_id, occurred_at),
            "scrubbed": True,
            "pii_counts": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0},
            "participants": _participants(case, comments, users, account_name),
            "turns": turns,
            "meta": {
                "withheld_comment_count": response["meta"]["withheld_comment_count"],
                "turn_count": len(turns),
                "soql": response["meta"]["soql"],
            },
        }
        validate(document, "SourceDocument")
        return document

    def _users(self, user_ids: list[str]) -> dict[str, dict[str, Any]]:
        distinct = sorted({uid for uid in user_ids if uid})
        if not distinct:
            return {}
        response = self._client.call(
            "sfdc_get_users", {"user_ids": distinct}, schema="SalesforceQueryResponse",
        )
        return {row["Id"]: row for row in response["records"]}


def _side(user: dict[str, Any] | None) -> str:
    if user is None:
        return "momentive"
    return "momentive" if user.get("UserType") == _STAFF_USER_TYPE else "client"


def _author_name(author_id: str, user: dict[str, Any] | None) -> str:
    # The schema wants a name and an unresolved author has none. The id is the honest
    # answer: it says which record could not be resolved instead of inventing a person.
    return (user or {}).get("Name") or author_id


def _turn(case: dict[str, Any], comment: dict[str, Any],
          users: dict[str, dict[str, Any]]) -> dict[str, Any]:
    author_id = comment["CreatedById"]
    user = users.get(author_id)
    return {
        "ref": {
            "case_id": case["Id"],
            "case_number": case["CaseNumber"],
            "comment_id": comment["Id"],
            "author_id": author_id,
            "author_name": _author_name(author_id, user),
            "created_at": comment["CreatedDate"],
        },
        "speaker_id": author_id,
        "speaker_side": _side(user),
        "text": comment["CommentBody"],
        # Salesforce has no sentence spans. Empty, never absent.
        "sentences": [],
    }


def _participants(case: dict[str, Any], comments: list[dict[str, Any]],
                  users: dict[str, dict[str, Any]],
                  account_name: str | None) -> list[dict[str, Any]]:
    """One participant per distinct published comment author, in first appearance order.

    A case whose comments are all private has no authors left to list, and the schema
    wants at least one participant, so the account standing behind the case is the
    participant. That is the party the case is about, and it invents no person.
    """
    seen: list[str] = []
    for comment in comments:
        if comment["CreatedById"] not in seen:
            seen.append(comment["CreatedById"])
    if seen:
        return [
            {
                "id": author_id,
                "name": _author_name(author_id, users.get(author_id)),
                "side": _side(users.get(author_id)),
                # Salesforce User carries no job title in the allowlist, and
                # UserType is a permission class, not a title. Null, not a guess.
                "title": None,
            }
            for author_id in seen
        ]
    return [{
        "id": case["Id"],
        "name": account_name or case["CaseNumber"],
        "side": "client",
        "title": None,
    }]
