"""The two mock MCP servers and the two source connectors.

The five enforcement rules from `contracts/mcp_tools.md` each get a test, because a
control nobody has watched fire is indistinguishable from a control that is not there.
Then one round trip per source, proving the document a reader would see: the right
speaker sides, the right account, the turn spans a citation resolves against, and the
count of what was withheld.

Everything runs against `tests/fixtures/b4`, a hand made corpus of two calls and two
cases in the contract layout, one of each under `traps/`. The real corpus is generated
elsewhere and these tests do not depend on it existing.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from digest.connectors import (  # noqa: E402
    AccountDirectory,
    GongConnector,
    McpToolClient,
    SalesforceConnector,
    SourceConnector,
    server_spec,
)
from digest.contracts import validate  # noqa: E402
from digest.errors import WindowViolation  # noqa: E402

MOCK_DIR = REPO / "tests" / "fixtures" / "b4"
WINDOW_FROM = "2026-09-08"
WINDOW_TO = "2026-09-11"
UNTIL = datetime.date(2026, 9, 11)

CALL_ID = "7782934451002"
TRAP_CALL_ID = "7782934451118"
CASE_ID = "5008W00002aQpLrQAK"
TRAP_CASE_ID = "5008W00002aQpLsQAK"

# The exact text of the one IsPublished=false comment in the fixture corpus. If this
# string is anywhere in the serialized response, rule 3 has failed.
PRIVATE_CANARY = "PRIVATE INTERNAL NOTE canary onetwothree"

GONG_TOOLS = ["gong_list_calls", "gong_get_calls_extensive", "gong_get_transcripts"]
SFDC_TOOLS = ["sfdc_query_cases", "sfdc_get_case", "sfdc_get_accounts", "sfdc_get_users"]

GONG_CALL_FIELDS = {
    "id", "url", "title", "scheduled", "started", "duration", "primaryUserId",
    "direction", "system", "scope", "media", "language", "workspaceId",
    "sdrDisposition", "clientUniqueId", "customData", "purpose", "meetingUrl",
    "isPrivate", "calendarEventId",
}
SFDC_CASE_FIELDS = {"Id", "CaseNumber", "AccountId", "Subject", "Status", "Priority",
                    "CreatedDate", "ClosedDate"}
SFDC_COMMENT_FIELDS = {"Id", "ParentId", "CommentBody", "IsPublished", "CreatedById",
                       "CreatedDate"}
SFDC_USER_FIELDS = {"Id", "Name", "UserType", "IsActive"}

WRITE_VERBS = re.compile(
    r"(create|update|delete|insert|upsert|write|set_|post_|patch_|put_|remove|purge)",
    re.IGNORECASE,
)


def _client(name: str, row_cap: int = 200) -> McpToolClient:
    return McpToolClient.for_server(name, mock_dir=MOCK_DIR, window_from=WINDOW_FROM,
                                    window_to=WINDOW_TO, row_cap=row_cap, root=REPO)


@pytest.fixture(scope="module")
def gong():
    with _client("gong") as client:
        yield client


@pytest.fixture(scope="module")
def salesforce():
    with _client("salesforce") as client:
        yield client


@pytest.fixture(scope="module")
def accounts() -> AccountDirectory:
    return AccountDirectory.from_mock_dir(MOCK_DIR)


# ---------------------------------------------------------------------------
# Rule 1: read only
# ---------------------------------------------------------------------------

def test_rule_1_only_the_contract_tools_are_registered(gong, salesforce):
    assert gong.list_tool_names() == GONG_TOOLS
    assert salesforce.list_tool_names() == SFDC_TOOLS


def test_rule_1_no_write_tool_exists(gong, salesforce):
    """Not a disabled write tool and not a gated one. There is no write tool."""
    for client in (gong, salesforce):
        for name in client.list_tool_names():
            assert not WRITE_VERBS.search(name), "%s looks like a write tool" % name


def test_rule_1_no_write_verb_is_registered_in_either_server_source():
    """The grep half of the proof: nothing registers a tool the client cannot see."""
    registered = []
    for source in ("mcp/gong_server.py", "mcp/salesforce_server.py"):
        text = (REPO / source).read_text(encoding="utf-8")
        registered.extend(re.findall(r'_tool\(\s*\w+,\s*"([a-z_]+)"', text))
    assert sorted(registered) == sorted(GONG_TOOLS + SFDC_TOOLS)
    assert not [name for name in registered if WRITE_VERBS.search(name)]


def test_a_missing_window_variable_is_a_boot_failure():
    """Defaulting a security boundary to everything is how it stops existing."""
    spec = server_spec("gong", mock_dir=MOCK_DIR, window_from=WINDOW_FROM,
                       window_to=WINDOW_TO, root=REPO)
    env = {"PATH": os.environ.get("PATH", ""), "DIGEST_MOCK_DIR": str(MOCK_DIR)}
    finished = subprocess.run([spec["command"], *spec["args"]], env=env,
                              capture_output=True, text=True, timeout=60)
    assert finished.returncode != 0
    assert "DIGEST_WINDOW_FROM" in finished.stderr
    assert "DIGEST_WINDOW_TO" in finished.stderr


# ---------------------------------------------------------------------------
# Rule 2: date window scoping
# ---------------------------------------------------------------------------

def test_rule_2_gong_refuses_a_wider_window(gong):
    arguments = {"from_date_time": "2026-09-01T00:00:00Z",
                 "to_date_time": "2026-09-30T23:59:59Z"}
    with pytest.raises(WindowViolation) as caught:
        gong.call("gong_list_calls", arguments)
    error = caught.value
    assert error.tool == "gong_list_calls"
    assert error.requested == {"from": "2026-09-01T00:00:00Z", "to": "2026-09-30T23:59:59Z"}
    assert error.allowed == {"from": "2026-09-08T00:00:00Z", "to": "2026-09-11T23:59:59Z"}


def test_rule_2_salesforce_refuses_a_wider_window(salesforce):
    with pytest.raises(WindowViolation) as caught:
        salesforce.call("sfdc_query_cases", {"created_from": "2026-09-01T00:00:00Z",
                                             "created_to": "2026-09-30T23:59:59Z"})
    assert caught.value.tool == "sfdc_query_cases"


def test_rule_2_the_refusal_message_names_both_windows(gong):
    """The message a human reads, and the prefix the connector keys on."""
    raw = gong._submit("call_tool", "gong_list_calls",
                       {"from_date_time": "2026-09-07T00:00:00Z",
                        "to_date_time": "2026-09-11T23:59:59Z"})
    assert raw.is_error
    text = raw.content[0].text
    assert text.startswith("window_violation:")
    assert "2026-09-07T00:00:00Z" in text
    assert "2026-09-08T00:00:00Z" in text
    assert "2026-09-11T23:59:59Z" in text


def test_rule_2_a_violation_is_refused_and_not_trimmed(gong):
    """The failure mode this guards against is a result set quietly shrinking to fit,
    which looks exactly like a quiet day."""
    with pytest.raises(WindowViolation):
        gong.call("gong_list_calls", {"from_date_time": "2026-09-01T00:00:00Z",
                                      "to_date_time": "2026-09-11T23:59:59Z"})
    inside = gong.call("gong_list_calls", {"from_date_time": "2026-09-08T00:00:00Z",
                                           "to_date_time": "2026-09-11T23:59:59Z"},
                       schema="GongCallsResponse")
    assert inside["meta"]["rows_returned"] == 2


def test_rule_2_an_id_outside_the_window_is_refused_too():
    """A narrower server must not hand over a record from a day it does not serve."""
    narrow = McpToolClient.for_server("gong", mock_dir=MOCK_DIR,
                                      window_from="2026-09-08", window_to="2026-09-08",
                                      root=REPO)
    with narrow:
        with pytest.raises(WindowViolation):
            narrow.call("gong_get_transcripts", {"call_ids": [TRAP_CALL_ID]})


# ---------------------------------------------------------------------------
# Rule 3: IsPublished = true is in the query
# ---------------------------------------------------------------------------

def test_rule_3_is_published_true_is_in_the_soql(salesforce):
    response = salesforce.call("sfdc_get_case", {"case_id": CASE_ID},
                               schema="SalesforceCaseResponse")
    assert "IsPublished = true" in response["meta"]["soql"]
    assert "WHERE" in response["meta"]["soql"]


def test_rule_3_the_withheld_count_is_right_and_no_private_row_returns(salesforce):
    response = salesforce.call("sfdc_get_case", {"case_id": CASE_ID},
                               schema="SalesforceCaseResponse")
    assert response["meta"]["withheld_comment_count"] == 1
    assert [c["IsPublished"] for c in response["comments"]] == [True, True]


def test_rule_3_the_private_body_is_not_in_the_response_bytes(salesforce):
    """Grep, not trust. The private comment sits in the same case file as the public
    ones and still never reaches the agent."""
    on_disk = (MOCK_DIR / "salesforce" / "cases" / ("%s.json" % CASE_ID)).read_text("utf-8")
    assert PRIVATE_CANARY in on_disk, "the fixture must carry a private comment to withhold"
    response = salesforce.call("sfdc_get_case", {"case_id": CASE_ID},
                               schema="SalesforceCaseResponse")
    assert PRIVATE_CANARY not in json.dumps(response, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Rule 4: field allowlist
# ---------------------------------------------------------------------------

def test_rule_4_gong_records_carry_exactly_the_allowlist(gong):
    response = gong.call("gong_list_calls",
                         {"from_date_time": "2026-09-08T00:00:00Z",
                          "to_date_time": "2026-09-11T23:59:59Z"},
                         schema="GongCallsResponse")
    assert set(response["meta"]["fields_allowlisted"]) == GONG_CALL_FIELDS
    for call in response["calls"]:
        assert set(call) == GONG_CALL_FIELDS
    extensive = gong.call("gong_get_calls_extensive", {"call_ids": [CALL_ID]},
                          schema="GongCallsExtensiveResponse")
    assert set(extensive["calls"][0]) == {"metaData", "parties"}


def test_rule_4_salesforce_records_carry_the_allowlist_plus_attributes(salesforce):
    cases = salesforce.call("sfdc_query_cases",
                            {"created_from": "2026-09-08T00:00:00Z",
                             "created_to": "2026-09-11T23:59:59Z"},
                            schema="SalesforceQueryResponse")
    for record in cases["records"]:
        assert set(record) == SFDC_CASE_FIELDS | {"attributes"}
    detail = salesforce.call("sfdc_get_case", {"case_id": CASE_ID},
                             schema="SalesforceCaseResponse")
    for comment in detail["comments"]:
        assert set(comment) == SFDC_COMMENT_FIELDS | {"attributes"}
    users = salesforce.call("sfdc_get_users", {"user_ids": ["0058W00000LmNoPQAV"]},
                            schema="SalesforceQueryResponse")
    assert set(users["records"][0]) == SFDC_USER_FIELDS | {"attributes"}


# ---------------------------------------------------------------------------
# Rule 5: row cap
# ---------------------------------------------------------------------------

def test_rule_5_the_row_cap_returns_exactly_the_cap_with_a_cursor():
    with _client("gong", row_cap=1) as capped:
        first = capped.call("gong_list_calls",
                            {"from_date_time": "2026-09-08T00:00:00Z",
                             "to_date_time": "2026-09-11T23:59:59Z"},
                            schema="GongCallsResponse")
        assert len(first["calls"]) == 1
        assert first["meta"]["row_cap"] == 1
        assert first["records"]["totalRecords"] == 2
        assert first["records"]["cursor"], "a capped page must say there is more"
        second = capped.call("gong_list_calls",
                             {"from_date_time": "2026-09-08T00:00:00Z",
                              "to_date_time": "2026-09-11T23:59:59Z",
                              "cursor": first["records"]["cursor"]},
                             schema="GongCallsResponse")
        assert len(second["calls"]) == 1
        assert second["records"]["cursor"] is None
        assert {c["id"] for c in first["calls"] + second["calls"]} == {CALL_ID, TRAP_CALL_ID}


def test_rule_5_the_cap_reaches_salesforce_soql_as_a_limit():
    with _client("salesforce", row_cap=1) as capped:
        response = capped.call("sfdc_query_cases",
                               {"created_from": "2026-09-08T00:00:00Z",
                                "created_to": "2026-09-11T23:59:59Z"},
                               schema="SalesforceQueryResponse")
        assert len(response["records"]) == 1
        assert response["meta"]["soql"].endswith("LIMIT 1")
        assert response["done"] is False


# ---------------------------------------------------------------------------
# Traps load through the same code path as generated fixtures
# ---------------------------------------------------------------------------

def test_a_trap_file_is_indistinguishable_from_a_generated_one(gong, salesforce):
    calls = gong.call("gong_list_calls",
                      {"from_date_time": "2026-09-08T00:00:00Z",
                       "to_date_time": "2026-09-11T23:59:59Z"},
                      schema="GongCallsResponse")
    assert {c["id"] for c in calls["calls"]} == {CALL_ID, TRAP_CALL_ID}
    cases = salesforce.call("sfdc_query_cases",
                            {"created_from": "2026-09-08T00:00:00Z",
                             "created_to": "2026-09-11T23:59:59Z"},
                            schema="SalesforceQueryResponse")
    assert {c["Id"] for c in cases["records"]} == {CASE_ID, TRAP_CASE_ID}


def test_users_are_the_union_of_the_generated_file_and_the_trap_file(salesforce):
    response = salesforce.call(
        "sfdc_get_users",
        {"user_ids": ["0058W00000LmNoPQAV", "0058W00000QqRsTQAV", "0058W00000ZzZzZQAV"]},
        schema="SalesforceQueryResponse",
    )
    found = {r["Id"]: r["UserType"] for r in response["records"]}
    assert found == {"0058W00000LmNoPQAV": "CustomerSuccess",
                     "0058W00000QqRsTQAV": "PowerPartner"}


# ---------------------------------------------------------------------------
# Connector round trips
# ---------------------------------------------------------------------------

def test_the_connectors_satisfy_the_protocol(gong, salesforce, accounts):
    assert isinstance(GongConnector(gong, accounts), SourceConnector)
    assert isinstance(SalesforceConnector(salesforce, accounts), SourceConnector)


def test_gong_list_since_covers_only_the_window(gong, accounts):
    connector = GongConnector(gong, accounts)
    everything = connector.list_since(None, UNTIL)
    assert [r["source_id"] for r in everything] == [CALL_ID, TRAP_CALL_ID]
    assert everything[0]["doc_type"] == "call"
    after_first_day = connector.list_since(datetime.date(2026, 9, 8), UNTIL)
    assert [r["source_id"] for r in after_first_day] == [TRAP_CALL_ID]


def test_gong_fetch_returns_a_valid_source_document(gong, accounts):
    document = GongConnector(gong, accounts).fetch(CALL_ID)
    validate(document, "SourceDocument")
    assert document["account_id"] == "ACC-0001"
    assert document["account_name"] == "Great Lakes Museum Alliance"
    assert document["meta"] == {"withheld_comment_count": 0, "turn_count": 2, "soql": None}
    assert [p["side"] for p in document["participants"]] == ["client", "momentive"]


def test_gong_turns_group_a_monologue_and_keep_its_sentences(gong, accounts):
    document = GongConnector(gong, accounts).fetch(CALL_ID)
    first = document["turns"][0]
    assert first["speaker_side"] == "client"
    assert first["ref"] == {"call_id": CALL_ID, "speaker_id": "4521",
                            "speaker_name": "Dana Ruiz", "affiliation": "External",
                            "start_ms": 418000, "end_ms": 437000}
    assert len(first["sentences"]) == 2
    assert first["sentences"][0]["start_ms"] == 418000
    assert first["sentences"][-1]["end_ms"] == 437000
    assert first["text"] == " ".join(s["text"] for s in first["sentences"])


def test_gong_unknown_affiliation_is_never_a_client(gong, accounts):
    """Trap T4(c) depends on this: an unresolvable speaker cannot produce a client claim."""
    document = GongConnector(gong, accounts).fetch(TRAP_CALL_ID)
    sides = {t["ref"]["affiliation"]: t["speaker_side"] for t in document["turns"]}
    assert sides["External"] == "client"
    assert sides["Unknown"] == "momentive"
    assert document["account_id"] == "ACC-0002"


def test_salesforce_fetch_returns_a_valid_source_document(salesforce, accounts):
    document = SalesforceConnector(salesforce, accounts).fetch(CASE_ID)
    validate(document, "SourceDocument")
    assert document["account_id"] == "ACC-0001"
    assert document["doc_type"] == "case"
    assert [t["speaker_side"] for t in document["turns"]] == ["client", "momentive"]
    assert all(t["sentences"] == [] for t in document["turns"])
    assert document["turns"][0]["ref"]["case_number"] == "00001042"


def test_salesforce_propagates_the_withheld_count_and_the_soql(salesforce, accounts):
    document = SalesforceConnector(salesforce, accounts).fetch(CASE_ID)
    assert document["meta"]["withheld_comment_count"] == 1
    assert "IsPublished = true" in document["meta"]["soql"]
    assert PRIVATE_CANARY not in json.dumps(document, ensure_ascii=False)


def test_salesforce_speaker_side_comes_from_user_type(salesforce, accounts):
    document = SalesforceConnector(salesforce, accounts).fetch(TRAP_CASE_ID)
    by_author = {t["ref"]["author_id"]: t["speaker_side"] for t in document["turns"]}
    assert by_author["0058W00000QqRsTQAV"] == "client"      # PowerPartner
    assert by_author["0058W00000ZzZzZQAV"] == "momentive"   # no user record resolves
    assert document["account_id"] == "ACC-0003"


def test_salesforce_list_since_is_sorted_and_window_scoped(salesforce, accounts):
    connector = SalesforceConnector(salesforce, accounts)
    refs = connector.list_since(None, UNTIL)
    assert [r["source_id"] for r in refs] == [CASE_ID, TRAP_CASE_ID]
    assert connector.list_since(datetime.date(2026, 9, 10), UNTIL)[0]["source_id"] == TRAP_CASE_ID


def test_the_account_directory_resolves_both_ways(accounts):
    assert accounts.by_domain("dana.ruiz@greatlakesmuseums.example.org") == (
        "ACC-0001", "Great Lakes Museum Alliance")
    assert accounts.by_domain("GREATLAKESMUSEUMS.EXAMPLE.ORG")[0] == "ACC-0001"
    assert accounts.by_sfdc_id("0018W00002HkLmPQAV") == (
        "ACC-0003", "Prairie Land Trust Council")
    assert accounts.by_domain("nobody.example.net") is None
    assert accounts.by_sfdc_id("0018W00002Missing") is None
