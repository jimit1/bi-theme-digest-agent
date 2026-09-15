"""Builds the tiny B4 fixture corpus and validates every file against the contract pack.

Two calls and two cases, one of each under `traps/`, in the layout of
`contracts/file_formats.md` section 12. Small on purpose: it exists to prove the five
enforcement rules and one connector round trip, not to stand in for the real corpus,
which other workers generate.

Run it from the repository root:

    .venv/bin/python tests/fixtures/b4/build_fixtures.py
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from digest.contracts import iter_errors  # noqa: E402

ACCOUNTS = {
    "schema_version": "1.0.0",
    "accounts": [
        {
            "account_id": "ACC-0001",
            "account_type": "customer",
            "domain": "greatlakesmuseums.example.org",
            "record": {
                "attributes": {"type": "Account",
                               "url": "/services/data/v62.0/sobjects/Account/0018W00002HkLmNQAV"},
                "Id": "0018W00002HkLmNQAV",
                "Name": "Great Lakes Museum Alliance",
                "Tier__c": "Enterprise",
                "ARR__c": 340000,
                "Renewal_Date__c": "2026-12-31",
                "Products__c": "membership;events;fundraising",
            },
        },
        {
            "account_id": "ACC-0002",
            "account_type": "customer",
            "domain": "cascadianurses.example.org",
            "record": {
                "attributes": {"type": "Account",
                               "url": "/services/data/v62.0/sobjects/Account/0018W00002HkLmOQAV"},
                "Id": "0018W00002HkLmOQAV",
                "Name": "Cascadia Nurses Association",
                "Tier__c": "Enterprise",
                "ARR__c": 268000,
                "Renewal_Date__c": "2027-03-31",
                "Products__c": "events;lms",
            },
        },
        {
            "account_id": "ACC-0003",
            "account_type": "customer",
            "domain": "prairielandtrust.example.org",
            "record": {
                "attributes": {"type": "Account",
                               "url": "/services/data/v62.0/sobjects/Account/0018W00002HkLmPQAV"},
                "Id": "0018W00002HkLmPQAV",
                "Name": "Prairie Land Trust Council",
                "Tier__c": "Professional",
                "ARR__c": 154000,
                "Renewal_Date__c": "2027-01-31",
                "Products__c": "membership;fundraising",
            },
        },
    ],
}


def _meta_data(call_id: str, title: str, scheduled: str, started: str,
               primary_user_id: str) -> dict:
    return {
        "id": call_id,
        "url": "https://gong.invalid/call?id=%s" % call_id,
        "title": title,
        "scheduled": scheduled,
        "started": started,
        "duration": 1840,
        "primaryUserId": primary_user_id,
        "direction": "Conference",
        "system": "Gong",
        "scope": "External",
        "media": "Video",
        "language": "eng",
        "workspaceId": "9911",
        "sdrDisposition": None,
        "clientUniqueId": None,
        "customData": None,
        "purpose": "Quarterly check in",
        "meetingUrl": None,
        "isPrivate": False,
        "calendarEventId": "cal-88213",
    }


CALL_ONE = {
    "schema_version": "1.0.0",
    "call": {
        "metaData": _meta_data("7782934451002",
                               "Great Lakes Museum Alliance quarterly check in",
                               "2026-09-08T15:00:00Z", "2026-09-08T15:01:12Z", "1187"),
        "parties": [
            {"id": "p-4521", "emailAddress": "dana.ruiz@greatlakesmuseums.example.org",
             "name": "Dana Ruiz", "title": "Director of Membership", "userId": None,
             "speakerId": "4521", "context": [], "affiliation": "External"},
            {"id": "p-1187", "emailAddress": "csm@momentive.invalid", "name": "Marcus Feld",
             "title": "Client Success Manager", "userId": "1187", "speakerId": "1187",
             "context": [], "affiliation": "Internal"},
        ],
    },
    "transcript": {
        "callId": "7782934451002",
        "transcript": [
            {"speakerId": "4521", "topic": "Renewals", "sentences": [
                {"start": 418000, "end": 430500,
                 "text": "Our renewal invoice came through with the full annual amount and "
                         "there is no line anywhere showing the dues we already paid in March."},
                {"start": 430500, "end": 437000,
                 "text": "We raised it in March and it has happened on every renewal since."},
            ]},
            {"speakerId": "1187", "topic": "Renewals", "sentences": [
                {"start": 437000, "end": 442250,
                 "text": "Let me pull the billing record and come back to you this week."},
            ]},
        ],
    },
}

CALL_TRAP = {
    "schema_version": "1.0.0",
    "call": {
        "metaData": _meta_data("7782934451118",
                               "Cascadia Nurses Association event operations review",
                               "2026-09-09T16:00:00Z", "2026-09-09T16:00:40Z", "1188"),
        "parties": [
            {"id": "p-6602", "emailAddress": "priya.nand@cascadianurses.example.org",
             "name": "Priya Nand", "title": "Events Manager", "userId": None,
             "speakerId": "6602", "context": [], "affiliation": "External"},
            {"id": "p-1188", "emailAddress": "ae@momentive.invalid", "name": "Owen Barrow",
             "title": "Account Executive", "userId": "1188", "speakerId": "1188",
             "context": [], "affiliation": "Internal"},
            {"id": "p-9001", "emailAddress": None, "name": "Unidentified speaker",
             "title": None, "userId": None, "speakerId": "9001", "context": [],
             "affiliation": "Unknown"},
        ],
    },
    "transcript": {
        "callId": "7782934451118",
        "transcript": [
            {"speakerId": "6602", "topic": "Events", "sentences": [
                {"start": 92000, "end": 101000,
                 "text": "The event check-in kiosk stalls whenever two staff scan badges at "
                         "the same desk at the same time."},
            ]},
            {"speakerId": "9001", "topic": "Events", "sentences": [
                {"start": 101000, "end": 106500,
                 "text": "A lot of associations ask us for a faster attendee kiosk."},
            ]},
        ],
    },
}

CASE_ONE = {
    "schema_version": "1.0.0",
    "case": {
        "attributes": {"type": "Case",
                       "url": "/services/data/v62.0/sobjects/Case/5008W00002aQpLrQAK"},
        "Id": "5008W00002aQpLrQAK",
        "CaseNumber": "00001042",
        "AccountId": "0018W00002HkLmNQAV",
        "Subject": "Renewal invoice missing prior dues credit",
        "Status": "Working",
        "Priority": "High",
        "CreatedDate": "2026-09-10T13:58:41.000Z",
        "ClosedDate": None,
    },
    "comments": [
        {"attributes": {"type": "CaseComment",
                        "url": "/services/data/v62.0/sobjects/CaseComment/00a8W00000XfT2mQAF"},
         "Id": "00a8W00000XfT2mQAF", "ParentId": "5008W00002aQpLrQAK",
         "CommentBody": "The credit from the part year membership never shows up, so finance "
                        "keeps having to raise a manual adjustment against every renewal.",
         "IsPublished": True, "CreatedById": "0058W00000LmNoPQAV",
         "CreatedDate": "2026-09-10T14:22:05.000Z"},
        {"attributes": {"type": "CaseComment",
                        "url": "/services/data/v62.0/sobjects/CaseComment/00a8W00000XfT2nQAF"},
         "Id": "00a8W00000XfT2nQAF", "ParentId": "5008W00002aQpLrQAK",
         "CommentBody": "PRIVATE INTERNAL NOTE canary onetwothree: if this drags on I would "
                        "put them at real risk of not renewing.",
         "IsPublished": False, "CreatedById": "0058W00000JkPqRQAV",
         "CreatedDate": "2026-09-10T15:02:11.000Z"},
        {"attributes": {"type": "CaseComment",
                        "url": "/services/data/v62.0/sobjects/CaseComment/00a8W00000XfT2oQAF"},
         "Id": "00a8W00000XfT2oQAF", "ParentId": "5008W00002aQpLrQAK",
         "CommentBody": "Billing has the record open and we will confirm the adjustment.",
         "IsPublished": True, "CreatedById": "0058W00000JkPqRQAV",
         "CreatedDate": "2026-09-10T16:10:00.000Z"},
    ],
}

CASE_TRAP = {
    "schema_version": "1.0.0",
    "case": {
        "attributes": {"type": "Case",
                       "url": "/services/data/v62.0/sobjects/Case/5008W00002aQpLsQAK"},
        "Id": "5008W00002aQpLsQAK",
        "CaseNumber": "00001043",
        "AccountId": "0018W00002HkLmPQAV",
        "Subject": "Dues credit not applied to the renewal notice",
        "Status": "New",
        "Priority": "Medium",
        "CreatedDate": "2026-09-11T09:12:00.000Z",
        "ClosedDate": None,
    },
    "comments": [
        {"attributes": {"type": "CaseComment",
                        "url": "/services/data/v62.0/sobjects/CaseComment/00a8W00000XfT3aQAF"},
         "Id": "00a8W00000XfT3aQAF", "ParentId": "5008W00002aQpLsQAK",
         "CommentBody": "Every renewal notice we send out still bills the full year even "
                        "after a mid year upgrade was paid for.",
         "IsPublished": True, "CreatedById": "0058W00000QqRsTQAV",
         "CreatedDate": "2026-09-11T09:40:12.000Z"},
        {"attributes": {"type": "CaseComment",
                        "url": "/services/data/v62.0/sobjects/CaseComment/00a8W00000XfT3bQAF"},
         "Id": "00a8W00000XfT3bQAF", "ParentId": "5008W00002aQpLsQAK",
         "CommentBody": "An author no user record resolves, so this one must read as "
                        "momentive rather than as a client.",
         "IsPublished": True, "CreatedById": "0058W00000ZzZzZQAV",
         "CreatedDate": "2026-09-11T10:05:00.000Z"},
    ],
}


def _user_response(users: list[dict], soql: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "totalSize": len(users),
        "done": True,
        "records": users,
        "meta": {
            "window": {"from": "2026-09-08T00:00:00Z", "to": "2026-09-11T23:59:59Z"},
            "rows_returned": len(users),
            "row_cap": 200,
            "withheld_comment_count": 0,
            "fields_allowlisted": ["Id", "Name", "UserType", "IsActive"],
            "soql": soql,
        },
    }


def _user(user_id: str, name: str, user_type: str) -> dict:
    return {
        "attributes": {"type": "User",
                       "url": "/services/data/v62.0/sobjects/User/%s" % user_id},
        "Id": user_id, "Name": name, "UserType": user_type, "IsActive": True,
    }


USERS = _user_response(
    [_user("0058W00000LmNoPQAV", "Dana Ruiz", "CustomerSuccess"),
     _user("0058W00000JkPqRQAV", "Marcus Feld", "Standard")],
    "SELECT Id, Name, UserType, IsActive FROM User LIMIT 200",
)

TRAP_USERS = _user_response(
    [_user("0058W00000QqRsTQAV", "Priya Nand", "PowerPartner")],
    "SELECT Id, Name, UserType, IsActive FROM User LIMIT 200",
)

INDEX = {
    "schema_version": "1.0.0",
    "generated_at": "2026-09-14T09:12:00Z",
    "seed": 20260914,
    "entries": [
        {"path": "gong/calls/7782934451002.json", "kind": "gong_call",
         "id": "7782934451002", "account_id": "ACC-0001",
         "occurred_at": "2026-09-08T15:00:00Z", "day": "2026-09-08", "week": "2026-W37",
         "theme_key": "renewal_invoice_credit", "trap": False},
        {"path": "traps/gong/calls/7782934451118.json", "kind": "gong_call",
         "id": "7782934451118", "account_id": "ACC-0002",
         "occurred_at": "2026-09-09T16:00:00Z", "day": "2026-09-09", "week": "2026-W37",
         "theme_key": "event_checkin_kiosk", "trap": True},
        {"path": "salesforce/cases/5008W00002aQpLrQAK.json", "kind": "sfdc_case",
         "id": "5008W00002aQpLrQAK", "account_id": "ACC-0001",
         "occurred_at": "2026-09-10T13:58:41Z", "day": "2026-09-10", "week": "2026-W37",
         "theme_key": "renewal_invoice_credit", "trap": False},
        {"path": "traps/salesforce/cases/5008W00002aQpLsQAK.json", "kind": "sfdc_case",
         "id": "5008W00002aQpLsQAK", "account_id": "ACC-0003",
         "occurred_at": "2026-09-11T09:12:00Z", "day": "2026-09-11", "week": "2026-W37",
         "theme_key": "renewal_invoice_credit", "trap": True},
    ],
}

FILES = [
    ("accounts.json", ACCOUNTS, "MockAccountsFile"),
    ("index.json", INDEX, "MockIndex"),
    ("gong/calls/7782934451002.json", CALL_ONE, "GongCallFile"),
    ("traps/gong/calls/7782934451118.json", CALL_TRAP, "GongCallFile"),
    ("salesforce/cases/5008W00002aQpLrQAK.json", CASE_ONE, "SalesforceCaseFile"),
    ("traps/salesforce/cases/5008W00002aQpLsQAK.json", CASE_TRAP, "SalesforceCaseFile"),
    ("salesforce/users.json", USERS, "SalesforceQueryResponse"),
    ("traps/users.json", TRAP_USERS, "SalesforceQueryResponse"),
]


def main() -> int:
    failures = []
    for relative, document, schema in FILES:
        errors = iter_errors(document, schema)
        if errors:
            failures.append("%s: %s" % (relative, "; ".join(errors)))
            continue
        path = HERE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    if failures:
        for line in failures:
            sys.stderr.write(line + "\n")
        return 1
    print("wrote %d fixture files under %s" % (len(FILES), HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
