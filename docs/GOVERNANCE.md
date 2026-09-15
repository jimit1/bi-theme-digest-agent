# Governance

This is the section for an IT and security reader at Momentive Software. Every control below
can be run, because a governance claim that cannot be demonstrated is a paragraph, not a
control. Run the commands from the code repository root with the store beside it at
`../bi-theme-digest-store`, written `$S` here. Numbers come from the sample run this build
ships with: 53 source documents, 55 claims, 11 themes, three weekly digests, reproducible
offline.

## The seven controls

| Control | Command | What it prints |
| --- | --- | --- |
| 1. PII removed before the model | `grep -h '"action": "scrub"' $S/runs/*/run.log.jsonl \| wc -l` and `grep -rl "Harold Pemberton-Vance" --exclude-dir=.git $S` | `53`, one scrub event per source document, each carrying counts only. The second prints nothing and exits 1: ten redactions were made (2 email, 2 phone, 2 address, 4 name) and no planted value survives anywhere in the store, audit log and raw sources included |
| 2. Every action audited, reads included | `grep -ho '"action": "[a-z_]*"' $S/runs/*/run.log.jsonl \| sort \| uniq -c \| sort -rn` | 1123 events across 20 runs: 565 reads, 218 writes, 61 model calls, 61 validations, 53 verifies, 53 scrubs, 47 scores, 33 proposals, 20 commits, 10 withholds, 2 approvals |
| 3. Private case comments never in the result set | `grep -c '"action": "withhold"' $S/runs/*/run.log.jsonl` | 10 withhold events across the 15 ingest runs, 4 in week 37, 5 in week 38, 1 in week 39 |
| 4. Structured output rejected, never patched | `cat $S/evidence/claims/*.jsonl \| wc -l` and `ls $S/evidence/rejected/` | `55` accepted, rejected empty. The run manifest carries a zero against each of `schema_invalid`, `citation_unresolved`, `speaker_not_client`, `duplicate`, `window_violation`, and every digest prints verified and rejected on its run line |
| 5. Every claim resolves to its source | `.venv/bin/python -m digest eval --mode replay` | 18 of 18 assertions pass, exit 0, assertion S1 reads `55 citations resolved` |
| 6. Least privilege at the tool boundary | `grep -n "def read_theme_index\|def read_theme\|def list_run_claims\|def read_account\|def write" src/digest/agents/editor/tools.py` | four lines, all reads, at 60, 66, 77 and 84. `def write` matches nothing |
| 7. A human gate before any system of record | `.venv/bin/python -m digest approve --theme THEME-0001 --dry-run --mode replay --repo OWNER/product-feedback` then the same without `--dry-run` | the first prints the issue title, body and ten row evidence table, files nothing, exits 0. The second exits 4 with `refused: --yes required` |

One scrub event in full, because the shape is the control:

```
{"agent": "scrubber", "action": "scrub", "target": "7782934451404", "outcome": "ok",
 "detail": {"EMAIL": 2, "PHONE": 2, "ADDRESS": 2, "NAME": 2}}
```

Reads are logged because "what did it touch" has to be answerable as a query, not a guess.
Control 3 is a query shape, not a filter: `IsPublished = true` is in the SOQL itself, so a
private comment is never in the result set the agent receives.

Drift is measured, not asserted, and that keeps the other seven honest over time.
`digest build --week 2026-W37 --stability --mode replay` asks for a second independent opinion
on the same claims. The two grouped every claim identically, Jaccard 1.000, and ranked a
different top three. I report that as measured rather than tuning until it looks tidy. Prompts
and schemas are versioned files, so a prompt change is a diff on a pull request.

## Least privilege

The editor is the agent holding the most context in the system and it has no tool that writes.
It proposes, the pipeline writes, a human files. The connectors are the same shape: read-only
tools only, not a disabled write tool and not a gated one, plus date window scoping that refuses
rather than trims, a field allowlist, and a row cap of 200 so a runaway loop cannot pull the
corpus. The agent cannot ask for what it is not allowed to see, because the tool will not form
the query. There is nothing to misconfigure, because the capability was never registered.

## Secrets

No credentials, tokens or keys in either repository, and no real email address other than mine
as the author. The demo runs on a Claude seat through the local CLI, so no API key exists on the
build machine at all. The only secret the workflows name is `STORE_TOKEN` for the commit step,
and both are green without it because the write step is skipped when it is absent. In production
the model and store credentials belong in a vault, scoped read-only per source, one identity per
agent.

## What leaves the tenant

Prompts go to the model provider. Nothing else leaves. No source data is stored outside the
context store: transcripts, case comments, claims, themes, digests, proposals and audit logs all
live there, and the prompts that carried them are recorded there too, which is what makes an
offline replay possible. The store is the only durable copy.

## Failure behavior

Rejection over repair, everywhere. Exit codes are a fixed mapping so a red job is readable
without opening the log: 0 ok, 1 unexpected, 2 contract violation (schema invalid, citation
unresolved, window violation), 3 replay miss, 4 refused by the gate or a read-only store, 5 eval
failure. A replay miss never falls back to a live call, because a silent fallback would spend
money and hide a prompt change.

The failure I care most about is not an error. It is a digest that looks normal and is missing a
day. Ingest reads a watermark and pulls only what is new, so a skipped night shows up as a thin
run: production wants a dead letter alarm on that job plus a floor on sources read per night.
Each digest prints a run line with sources read, comments withheld, redactions, claims verified
and rejected, themes appended and opened, and cost, so a thin week is visible on the page a
product manager already reads.

## Kill switch

Disable the two workflows in the Actions tab, `ingest` and `digest`, and the agent stops at its
next tick. Revoke the store credential and it cannot write even if triggered by hand.
`DIGEST_STORE_READONLY=1` is the softer version: the run proceeds, the commit is logged with
outcome `withheld`, nothing is written. Nothing here holds a standing connection or a queue that
keeps draining after the switch is thrown.

## Cost caps

The caps in configuration today are per-tier `max_tokens` in `config/models.yaml` (4000
extraction, 16000 synthesis, 8000 narrative) and `DIGEST_ROW_CAP`, default 200. A per-run dollar
cap belongs beside them in production and is named in `docs/PRODUCTION_CONTEXT.md` rather than
built here, because the scheduler is the right place to enforce it. Measured: 5.47 USD for the
whole three weeks by the pricing table, 6.69 USD by the provider's own accounting, against the
20 USD ceiling I set myself. Per week that is 2.27, 1.03 and 0.95 USD, ingest plus build. Week
37 re-run on the cheap tier map costs 23 percent of that and groups the claims identically.

## NIST AI RMF

Govern is the human gate, the versioned prompts and schemas, and the kill switch. Map is the
tool boundary, the field allowlist and the three-layer context store that defines what each
agent can see. Measure is the audit log, the golden set eval, citation verification and the
drift number. Manage is reject over repair, the exit code contract, the thin run alarm and the
cost caps.
