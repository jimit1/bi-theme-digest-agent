"""Deterministic per account enrichment. No model touches this file.

`enrich` produces one `Enrichment.schema.json` document per requested account id from two
Salesforce reads: `sfdc_get_accounts` for the org specific tier, ARR and renewal fields, and
one `sfdc_query_cases` sweep over the corpus window for open case counts. Everything here is
a join or arithmetic, never a judgement call, which is why no model is in this path.

Two ids meet in this file and neither one is optional:

- `ACC-nnnn`, the pipeline's own account id, used everywhere else in the system (Claim,
  Theme, Enrichment).
- The Salesforce record `Id`, an 18 (or 15) character string, which is what the Salesforce
  tools actually take and return.

`account_type` and the `ACC-nnnn` <-> Salesforce `Id` mapping are not Salesforce fields:
they live in the mock accounts file, outside the Account record, for the same reason
`AccountDirectory.domain` does (see `digest.connectors.base` and the account resolution
assumption in `contracts/README.md`). This module reads that file directly rather than
through `AccountDirectory`, because `AccountDirectory`'s public surface (`by_domain`,
`by_sfdc_id`) answers a different question: it maps a Gong email domain or a Salesforce
account id to `(account_id, name)` for connector use, and does not expose `account_type` or
a reverse `account_id -> Salesforce Id` lookup. Reading the same file a second, narrower way
is cheaper than widening a class two other modules already depend on for something this
module owns exclusively.

`sfdc_connector` is expected to expose the same public surface `digest.connectors.mcp_client.
McpToolClient` does: `.call(tool_name, arguments, schema=schema_name)` returning the parsed,
validated JSON document, and a `.window` property of `{"from": ..., "to": ...}` giving the
corpus's configured date bounds. That is a narrower ask than the full `SalesforceConnector`,
which exposes only `list_since`/`fetch` and has no method for `sfdc_get_accounts` or
`sfdc_query_cases`; `digest.enrich` is the reader named for `SalesforceQueryResponse.schema.
json` in `contracts/README.md`, so it calls those two tools itself.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from digest.contracts import validate

__all__ = ["enrich"]

_TIER_MAP = {
    "Enterprise": "enterprise",
    "Professional": "professional",
    "Standard": "standard",
    "Prospect": "prospect",
}


def _mock_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DIGEST_MOCK_DIR") or "data/mock")


def _load_account_index() -> dict[str, dict[str, Any]]:
    """`ACC-nnnn` -> the full mock accounts.json entry (account_type, domain, record)."""
    path = _mock_dir() / "accounts.json"
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    validate(document, "MockAccountsFile")
    return {entry["account_id"]: entry for entry in document["accounts"]}


def _products(products_field: str) -> list[str]:
    if not products_field:
        return []
    # dict.fromkeys rather than set(): stable order, and Products__c is small enough that
    # order matching the picklist's own order is worth keeping for a human reading the file.
    return list(dict.fromkeys(part for part in products_field.split(";") if part))


def enrich(account_ids: list[str], sfdc_connector: Any) -> dict[str, dict[str, Any]]:
    """Build one `Enrichment` document per account id in `account_ids`.

    One `sfdc_get_accounts` call for the whole list, one `sfdc_query_cases` sweep of the
    corpus window for open case counts. `open_case_ids` are the cases on that account whose
    `Status` is not `Closed`; an unknown account id raises `KeyError`.
    """
    unique_ids = sorted(set(account_ids))
    if not unique_ids:
        return {}

    accounts_by_acc_id = _load_account_index()
    missing = [acc_id for acc_id in unique_ids if acc_id not in accounts_by_acc_id]
    if missing:
        raise KeyError(missing[0])

    sfdc_id_by_acc_id = {
        acc_id: accounts_by_acc_id[acc_id]["record"]["Id"] for acc_id in unique_ids
    }
    sfdc_ids = sorted(set(sfdc_id_by_acc_id.values()))

    accounts_response = sfdc_connector.call(
        "sfdc_get_accounts", {"account_ids": sfdc_ids}, schema="SalesforceQueryResponse",
    )
    account_record_by_sfdc_id = {
        row["Id"]: row for row in accounts_response["records"]
        if row.get("attributes", {}).get("type") == "Account"
    }

    window = sfdc_connector.window
    cases_response = sfdc_connector.call(
        "sfdc_query_cases",
        {"created_from": window["from"], "created_to": window["to"]},
        schema="SalesforceQueryResponse",
    )
    wanted_sfdc_ids = set(sfdc_ids)
    open_case_ids_by_sfdc_id: dict[str, list[str]] = {sfdc_id: [] for sfdc_id in sfdc_ids}
    for row in cases_response["records"]:
        if row.get("attributes", {}).get("type") != "Case":
            continue
        account_sfdc_id = row["AccountId"]
        if account_sfdc_id in wanted_sfdc_ids and row["Status"] != "Closed":
            open_case_ids_by_sfdc_id[account_sfdc_id].append(row["Id"])

    result: dict[str, dict[str, Any]] = {}
    for acc_id in unique_ids:
        sfdc_id = sfdc_id_by_acc_id[acc_id]
        record = account_record_by_sfdc_id.get(sfdc_id)
        if record is None:
            raise KeyError(acc_id)
        open_case_ids = sorted(open_case_ids_by_sfdc_id.get(sfdc_id, []))
        enrichment = {
            "schema_version": "1.0.0",
            "account_id": acc_id,
            "account_name": record["Name"],
            "account_type": accounts_by_acc_id[acc_id]["account_type"],
            "tier": _TIER_MAP[record["Tier__c"]],
            "arr_usd": float(record["ARR__c"]),
            "renewal_date": record["Renewal_Date__c"],
            "open_case_count": len(open_case_ids),
            "open_case_ids": open_case_ids,
            "products": _products(record["Products__c"]),
        }
        validate(enrichment, "Enrichment")
        result[acc_id] = enrichment
    return result
