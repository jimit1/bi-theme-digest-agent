# How this agent gathers its own context in production

Drew asked me to show how the agent would gather its own context in production, not just
how it runs on my laptop. This is that answer, written for the version that runs inside
Momentive Software on a schedule with nobody watching it. Everything below is either already
in the repository or is a named, sized change I can point at. Where it is documented
rather than built, I say so in the line itself.

## The schedule, and why it is incremental

Two workflows are committed in `.github/workflows/` and both are runnable from the
Actions tab. `ingest.yml` runs on cron `0 6 * * *`, so nightly at 06:00 UTC, and pulls
the previous day's calls and cases. `digest.yml` runs on cron `0 7 * * 1`, so Mondays at
07:00 UTC, and runs the editor over the week, scores the themes, writes the digest and
the HTML page, and opens proposals. Both carry `workflow_dispatch` so a person can
trigger them by hand, and both run in replay mode against the committed corpus, so they
are green with no secret configured. That is deliberate and it is stated as a comment in
the workflow file.

Ingestion never re-reads the corpus. It reads a watermark off the store, in
`sources/_INDEX.md`, which carries `last_ingest_run` and `last_ingest_day`, and it pulls
only what is newer than that. The entry point is `ingest --since-watermark`. In the
sample run that is fifteen nightly ingests over three corpus weeks producing 55 claims
from 53 source documents, and the per-day claim counts range from 11 down to 1, with one
day at zero. Nothing is fetched twice, and nothing already in the store is regenerated.

## The connectors are the same tools, pointed somewhere real

The pipeline never opens a mock file. It calls a tool. Two local MCP servers,
`mcp/gong_server.py` and `mcp/salesforce_server.py`, serve the mock corpus over the MCP
protocol, and they advertise exactly seven tools: `gong_list_calls`,
`gong_get_calls_extensive`, `gong_get_transcripts`, `sfdc_query_cases`, `sfdc_get_case`,
`sfdc_get_accounts` and `sfdc_get_users`. In production those same seven names are backed
by the real APIs. Gong: `GET /v2/calls` for call metadata by date range,
`POST /v2/calls/extensive` for the participant list that maps a speaker id to a person,
and `POST /v2/calls/transcript` for the transcripts. Salesforce: SOQL through the REST
query endpoint at `/services/data/v62.0/query`, over `Case`, `CaseComment`, `Account` and
`User`. The mock serves the real response shapes, including the cursor pagination, so the
change is a base URL plus a credential and there is no translation layer to write.

Five rules are enforced at the tool boundary and not in a prompt. There is no write tool
to call, not a disabled one and not a gated one. The date window comes from the launcher
environment and a request outside it is refused rather than trimmed. `IsPublished = true`
is in the SOQL itself, so a private case comment is never in the result set the agent
receives, and the count of comments withheld comes back in response metadata: ten of them
across the sample run. There is a field allowlist and a row cap. The sentence I care about
is that the agent cannot ask for what it is not allowed to see, because the tool will not
form the query.

## Credentials, identity and blast radius

One read-only credential per source, scoped at the source. For Gong that is an API key
with read scopes on calls and transcripts only. For Salesforce it is a connected app whose
profile has read on those four objects and nothing else, with the field-level security
matching the allowlist, so least privilege is enforced twice: once by the platform and
once by the tool.

One identity per agent, not one shared service account, because an audit log that says
"the integration user did it" answers nothing. Secrets live in a vault, read at start-up
and never written to disk, never in the repository and never in a log line. The store
credential is scoped to one repository and one repository only. That matters because the
store is a separate repository, `bi-theme-digest-store`, with no code in it and no secrets
in it. Two consequences: `git log` there is a pure audit trail of pipeline commits, 23 of
them in the sample run, and the blast radius of a compromised agent credential is one
repository that contains nothing worth taking.

## Scrubbing before the model, and what the audit log keeps

Every fetched document goes through the scrubber before it is stored and before any model
sees it. The document is only ever persisted scrubbed. In the sample run that is ten
redactions: two email addresses, two phone numbers, two postal addresses and four personal
names. The eval asserts that none of those values appears anywhere in the store, and that
assertion passes.

The audit log is `runs/<run_id>/run.log.jsonl`, one validated event per line, flushed as
it goes. It records reads, so a source the agent looked at is logged even when nothing came
of it. It records withholding as a number, so the private comments show up as a count and
not as silence. It records scrub events as counts by kind, never the value that was
scrubbed, which is the one rule the code enforces rather than asserts. It records every
model call with the stage, the prompt hash, the model id, tokens and cost, and it records
rejections with a reason code. Two implications I care about: any digest can be explained
after the fact, and nothing sensitive is in the log itself.

## The store is memory, so the digest is not rebuilt from scratch

The editor reads `themes/_INDEX.md` first, one line per theme, and opens a theme file only
when the index says it is relevant. That is progressive disclosure, and because layer two
can be gated by role it is least privilege by construction. The practical effect is visible
in the weekly numbers. Week 37 opened ten themes because the store was empty. Week 38
appended seven claims to themes that already existed and opened exactly one new one. Week
39 appended eight and opened none, with three themes marked quiet and three past the
fourteen day verify horizon. A theme with no new evidence goes quiet and then stale, and any
agent reading a stale file says so. Week 39 cost 0.4586 USD against week 37's 1.2187 USD,
which is what not regenerating looks like on the invoice.

The golden set is seven hand-written assertions today and eighteen assertions as it stands
after the build, all eighteen passing. In production it grows from the digests themselves:
every human correction becomes a labelled example, every rejected claim becomes a negative
case, and every incident becomes a permanent regression test. It is versioned in the store,
so the eval history is as auditable as the digest history.

## Drift, and the failure that does not look like one

Drift is measured, not asserted. Week over week I compare this digest's themes against last
week's, and on a rerun of the same week I report claim-to-theme agreement and whether the
top three is stable. The sample run agreed on every claim-to-theme assignment, a Jaccard of
1.000, and ranked a different top three. I publish that rather than hide it, because a
measured imperfection reads as engineering and a claimed perfection reads as marketing.

The alarm I actually want is on thin runs. The worst outcome for a digest agent is not an
error, it is a digest that looks normal and is quietly missing a day of calls. So ingestion
alerts on a day whose claim count falls outside its own recent range, not only on a failed
job, and a run that rejects more than a configured fraction of claims fails loudly instead
of shipping a thin week.

## Nothing reaches a system of record without a person

The agent proposes. It does not file. Proposals sit unapproved in `proposals/<week>/`, and
`approve` refuses to do anything without an explicit `--yes`, exiting 4 if it is missing.
A dry run prints the issue title, the body and the evidence table and files nothing. The
write path to any system of record is one human decision wide, and that is the tier the
agent stays at until the acceptance rate of its proposals is a number rather than a feeling.

## The AWS path, documented and not built

If this runs in an AWS account rather than on Actions, it is EventBridge Scheduler
triggering a Fargate task or a Lambda on the same two entry points, `ingest` and `build`,
with no code change. The store credential and the model credential move to Secrets Manager.
Each run carries a cost cap, checked against the per-run figures the pipeline already
reports. The ingest job gets a dead letter queue with an alarm on it, so a silent failure is
caught that night and not a week later in a digest that reads fine. I have not built this,
because the prototype proves the pipeline and Actions proves the schedule, and standing up
an account would have proven neither.

## The operating rule

Read broadly, act narrowly, widen on evidence. The agent is allowed to see a lot, because a
digest that misses the call where the customer said the thing is worthless. It is allowed to
change almost nothing, because that is where the risk lives. And it earns more room only
against a measured record, never against time served.
