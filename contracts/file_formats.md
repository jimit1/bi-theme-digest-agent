# File formats, ids and the calendar

Everything here is pinned. Where a format is a line of text rather than a JSON document it
comes with a regex, because two workers reading the same sentence differently is exactly
how a parallel build fails at integration.

## 1. Identifier rules

### ClaimId

```
claim_id = sha256( canonical_json(source_ref) + verbatim )[:12]
```

- `canonical_json(source_ref)` is `json.dumps(source_ref, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- `source_ref` is the FULL ref as stored in the Claim, after code has filled `speaker_name`
  and `affiliation` (Gong) or `case_number`, `author_id`, `author_name` and `created_at`
  (Salesforce). Hash what is stored, so a reviewer can recompute the id from the claim alone.
- The two parts are encoded UTF-8 and concatenated with no separator, then hashed.
- Take the first 12 characters of the lowercase hex digest. Pattern `^[0-9a-f]{12}$`.

Reference implementation and test vector:

```python
import hashlib, json

def claim_id(source_ref: dict, verbatim: str) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(source_ref, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False).encode("utf-8"))
    h.update(verbatim.encode("utf-8"))
    return h.hexdigest()[:12]
```

`contracts/examples/Claim.example.json` carries a claim_id computed by exactly this function
from exactly the `source_ref` and `verbatim` in that file. It is the fixture to test against.

### ThemeId

`THEME-` plus a four digit zero padded counter. Pattern `^THEME-\d{4}$`. Assigned by code,
never by a model. The counter continues from the highest id present in `themes/_INDEX.md`,
starting at `THEME-0001` on an empty store. Within one build, ids are assigned to the
editor's `new_themes` placeholders in ascending numeric order of the placeholder
(`NEW-1`, then `NEW-2`, then `NEW-3`), so a rerun of the same input produces the same ids.
That property is an eval assertion, not a hope.

### Placeholders

`^NEW-[1-9]\d*$`. Only ever appear inside an `EditorProposal`. They never reach disk.

### Run ids

| Kind | Format | Example | Covers |
|---|---|---|---|
| Ingest | `<YYYY-MM-DD>T06:00Z` | `2026-09-08T06:00Z` | the calendar day named in the id |
| Build | `<Monday after the week>T07:00Z` | `2026-09-14T07:00Z` | the week that ended the day before |

Pattern for either: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$`. Note there are no seconds. A run id is
an identifier, not a timestamp; timestamps inside documents are full ISO 8601.

### Week label

`2026-W37`. Pattern `^\d{4}-W\d{2}$`. ISO week number, zero padded.

### Account id

`ACC-` plus four digits. Pattern `^ACC-\d{4}$`. Assigned in `data/mock/accounts.json` and
stable for the life of the corpus. `ACC-0001` through `ACC-0006` are customers, `ACC-0007`
through `ACC-0009` are prospects.

### Proposal id

`<week>/<theme_id>`, for example `2026-W37/THEME-0003`. Pattern
`^\d{4}-W\d{2}/THEME-\d{4}$`. It is the path of the proposal file under `proposals/`, without
the extension.

### Prompt hash and replay key

Both are truncated sha256 over fields joined by the ASCII unit separator, U+001F:

```
prompt_hash   = sha256("\x1f".join([system, user, schema_name]).encode("utf-8"))[:16]
replay_key    = sha256("\x1f".join([tier, system, user, schema_name]).encode("utf-8"))[:16]
```

Both patterns are `^[0-9a-f]{16}$`. The separator is pinned because a different joiner
produces a different key and the committed replay corpus would stop resolving.

## 2. The calendar, pinned

| Week | Monday | Sunday | Ingestion days | Build run id |
|---|---|---|---|---|
| `2026-W37` | 2026-09-07 | 2026-09-13 | 09-07, 09-08, 09-09, 09-10, 09-11 | `2026-09-14T07:00Z` |
| `2026-W38` | 2026-09-14 | 2026-09-20 | 09-14, 09-15, 09-16, 09-17, 09-18 | `2026-09-21T07:00Z` |
| `2026-W39` | 2026-09-21 | 2026-09-27 | 09-21, 09-22, 09-23, 09-24, 09-25 | `2026-09-28T07:00Z` |

Fifteen ingestion days, Monday to Friday. `python -m digest demo` runs ingest for all
fifteen and build for all three weeks, in date order. The W37 build happens on 2026-09-14 at
07:00Z, an hour after the 2026-09-14 ingest at 06:00Z, which is why the two suffixes differ.

## 3. The verify horizon, stated once

**Fourteen days from `last_verified`.**

- `stale = (build date - last_verified) > 14 days`. When `stale` is true, `stale_reason` is a
  sentence naming the age, and any agent reading the file says so.
- `status = quiet` when the theme received no evidence in the build window and its newest
  evidence is more than 14 days old, that is `score_inputs.recency_days > 14`, and the status
  is not already `filed`.
- `last_verified` is set to the build date whenever a theme receives new evidence in that
  build. A theme that receives nothing keeps its old `last_verified` and ages into `stale`.

This is the only place the horizon is defined. `digest.score`, `digest.store`,
`digest.render` and the golden set all quote this section rather than restating the number.

## 4. `themes/_INDEX.md`

Layer 1 of the store. One line per theme. This is what the editor reads first, and the only
thing it reads before it asks for specific themes by id.

```markdown
---
schema_version: "1.0.0"
owner: ai-operations
source: synthesized
last_verified: 2026-09-14
run_id: 2026-09-14T07:00Z
---

# Theme index

| id | title | product_area | status | score | accounts | evidence | last_updated_run | aliases |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| THEME-0003 | Renewal invoices do not show prior dues credit | membership | open | 74 | 2 | 5 | 2026-09-14T07:00Z | dues proration; credit on renewal; invoice credit line |
| THEME-0001 | Report exports truncate above ten thousand rows | reporting | open | 61 | 2 | 4 | 2026-09-14T07:00Z | export cap; report truncation |
```

Rules:

- The header row and the separator row are byte for byte as shown.
- One space after and before every pipe. No trailing spaces.
- `accounts` and `evidence` are counts, not lists.
- `aliases` are joined by `"; "`, a semicolon and one space. An empty alias list renders as
  a single `-`.
- `title` and every alias must contain no pipe and no newline. Replace a pipe with a slash
  when writing.
- Sort order is `score` descending, then `theme_id` ascending. Pinned, because a reordering
  diff on every run destroys the audit value of the store's git history.

Regex for one line (Python, on a single line of the file):

```
^\| (THEME-\d{4}) \| ([^|\n]{1,200}) \| (membership|events|fundraising|lms|jobs|accounting|integrations|reporting) \| (open|quiet|filed) \| (\d{1,3}) \| (\d+) \| (\d+) \| (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z) \| ([^|\n]{0,400}) \|$
```

Groups in order: `theme_id`, `title`, `product_area`, `status`, `score`, `accounts_count`,
`evidence_count`, `last_updated_run`, `aliases_joined`.

`ThemeIndexLine` as a Python object is a `TypedDict` with exactly those nine keys, the three
numeric ones as `int`, `aliases` as `list[str]` after splitting on `"; "` (and `[]` when the
cell is `-`). See `INTERFACES.md`.

## 5. `themes/<theme_id>.md`

YAML frontmatter that validates against `Theme.schema.json`, then a markdown body. The body
is written by code from the editor's rationale and the evidence list; the model never writes
a file.

```markdown
---
schema_version: "1.0.0"
theme_id: THEME-0003
title: Renewal invoices do not show prior dues credit
aliases: [dues proration, credit on renewal, invoice credit line]
product_area: membership
status: open
owner: ai-operations
source: synthesized
last_verified: 2026-09-14
run_id: 2026-09-14T07:00Z
created_run: 2026-09-14T07:00Z
last_updated_run: 2026-09-14T07:00Z
accounts: [ACC-0001, ACC-0003]
evidence: [e7e3c117f5c5, df11dfd159ae]
score: 74
score_inputs: {distinct_customers: 2, distinct_prospects: 0, arr_sum: 494000, open_cases: 3, recency_days: 1, claim_count: 2, high_importance_count: 2}
rationale: "one paragraph, written by the editor, grounded only in the evidence listed above"
stale: false
stale_reason: null
last_evidence_at: 2026-09-10T14:22:05.000Z
proposal_id: 2026-W37/THEME-0003
filed_issue_url: null
---

## Why this matters

<the editor's rationale, verbatim>

## Evidence

| claim_id | account | source | moment | verbatim |
| --- | --- | --- | --- | --- |
| e7e3c117f5c5 | Great Lakes Museum Alliance | gong | call 7782934451002 at 06:58, Dana Ruiz | ... |
| df11dfd159ae | Prairie Land Trust Council | salesforce | case 00001042 comment 00a8W00000XfT2mQAF | ... |
```

`run_id` is the `StoreFrontmatter` field and always equals `last_updated_run`. Both are
present so that one frontmatter reader serves every stored markdown file in the repository.

## 6. `sources/_INDEX.md`, the watermark

The incremental ingestion answer lives here. Ingest reads `last_ingest_day`, asks the
connectors for everything after it, and never re-reads a day it already has.

```markdown
---
schema_version: "1.0.0"
owner: ai-operations
source: pipeline
last_verified: 2026-09-11
run_id: 2026-09-11T06:00Z
last_ingest_run: 2026-09-11T06:00Z
last_ingest_day: 2026-09-11
---

# Ingested sources

| source | source_id | account_id | doc_type | occurred_at | ingest_run | turns | withheld |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gong | 7782934451002 | ACC-0001 | call | 2026-09-08T15:00:00Z | 2026-09-08T06:00Z | 42 | 0 |
| salesforce | 5008W00002aQpLrQAK | ACC-0003 | case | 2026-09-10T13:58:41Z | 2026-09-10T06:00Z | 6 | 1 |
```

Frontmatter regexes:

```
^last_ingest_run: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z)$
^last_ingest_day: (\d{4}-\d{2}-\d{2})$
```

Row regex:

```
^\| (gong|salesforce) \| ([A-Za-z0-9]{1,40}) \| (ACC-\d{4}) \| (call|case) \| (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})) \| (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z) \| (\d+) \| (\d+) \|$
```

Groups: `source`, `source_id`, `account_id`, `doc_type`, `occurred_at`, `ingest_run`,
`turn_count`, `withheld_comment_count`. Sort order is `occurred_at` ascending then
`source_id` ascending. Appending in that order keeps the git diff of an ingest run to the
lines it actually added.

`withheld` is the count of `IsPublished = false` comments that never entered the result set.
It is zero for every Gong row. This is the number that makes the T4(a) control demonstrable
rather than asserted.

## 7. `sources/<source_id>.json`

The scrubbed `SourceDocument` for one call or case, exactly as the reader agent saw it,
written by ingest and validated against `SourceDocument.schema.json`. This is what the
renderer reads to expand a claim into its source moment with neighbouring context, and what
the independent citation audit resolves against.

Filenames do not collide: a Gong `source_id` is all digits and a Salesforce Case Id is an 18
character alphanumeric starting with `500`. Nothing here is raw: every file has already been
through the scrubber, which is why a public store repository is safe.

## 8. `evidence/claims/<run_id>.jsonl` and `evidence/rejected/<run_id>.jsonl`

One JSON document per line, no blank lines, newline terminated, UTF-8, `ensure_ascii=False`.
Append only. Claims validate against `Claim.schema.json`, rejections against
`RejectedClaim.schema.json`. A run id contains a colon, which is legal in a filename on every
platform this runs on; the files are named `2026-09-08T06:00Z.jsonl`.

## 9. `proposals/<week>/<theme_id>.md`

What the editor proposes for filing, sitting unapproved until a human runs `approve`.

```markdown
---
schema_version: "1.0.0"
theme_id: THEME-0003
week: 2026-W37
run_id: 2026-09-14T07:00Z
status: proposed
filed_issue_url: null
owner: ai-operations
source: synthesized
last_verified: 2026-09-14
---

# Renewal invoices do not show prior dues credit

<the editor's file_proposals[].body, verbatim>

## Why it was proposed

<the editor's file_proposals[].reason, verbatim>

## Evidence

<one line per claim, each with its call second or case comment>
```

`status` is one of `proposed`, `approved`, `filed`. It moves to `filed` and
`filed_issue_url` is set only by `digest.gate.approve`, only when a human passed `--yes`.
A new theme's placeholder is resolved to a real theme id before the file is written, so no
`NEW-n` ever reaches disk.

## 10. `StoreFrontmatter`

Every stored markdown file in the store repository carries these five keys, first, in this
order:

```yaml
schema_version: "1.0.0"
owner: ai-operations
source: synthesized | pipeline | imported
last_verified: YYYY-MM-DD
run_id: <run id>
```

`ROUTER.md`, `themes/_INDEX.md`, `themes/*.md`, `sources/_INDEX.md`, `proposals/**/*.md` and
`digests/*.md` all carry it. Files that carry extra keys (a theme, the watermark, a proposal)
put them after these five. The verify horizon in section 3 is defined against `last_verified`
from this block.

## 11. `digests/<week>.md` and `digests/<week>.html`

The markdown digest carries `StoreFrontmatter` plus `week` and `run_id`. The HTML is a
single file with inline CSS and inline JavaScript and no network requests of any kind, so it
opens from a file path on a laptop with no internet. Every claim in it expands to its source
moment. See `INTERFACES.md` under `digest.render` for exactly what is shown.

## 12. The mock corpus on disk

Decided here, once, so the generator, the trap author and both MCP servers agree.

```
data/mock/
  seed_spec.yaml                      CorpusSeedSpec
  accounts.json                       MockAccountsFile
  pii_names.json                      PiiNames
  index.json                          MockIndex
  gong/calls/<call_id>.json           GongCallFile
  salesforce/cases/<case_id>.json     SalesforceCaseFile
  salesforce/users.json               SalesforceQueryResponse of User
  traps/gong/calls/<call_id>.json           GongCallFile, hand written
  traps/salesforce/cases/<case_id>.json     SalesforceCaseFile, hand written
```

Four decisions worth stating:

1. **One file per call, not two.** A `GongCallFile` holds the extensive record and the
   transcript together. A fetch is one logical object; two files drift and nobody notices
   until a citation stops resolving.
2. **A case file holds ALL its comments, including `IsPublished: false` ones.** The connector
   is what filters, and a control you cannot see fire is not a control. The MCP server reads
   the false rows, counts them, and never returns one.
3. **Traps live under `traps/` in the identical directory shape.** The servers load
   `gong/calls/*.json` and `traps/gong/calls/*.json` through the same code path, so a trap
   fixture is indistinguishable from a generated one at read time. `make data` regenerates
   the non trap corpus and never touches `traps/`.
4. **`index.json` lists every file with its date**, including the trap files, so a connector
   can apply a date window without opening every file. The generator writes the trap entries
   from `seed_spec.trap_slots` even though it does not write the trap files themselves. That
   removes the only ordering dependency between the corpus author and the trap author.
   `entries[].account_id` is for corpus QA only: a connector must resolve the account from
   the Gong party email domain or `Case.AccountId`, because that resolution is part of what
   is being demonstrated.

## 13. The corpus plan, pinned

Nine accounts: six customers with annual recurring revenue from 18,000 to 340,000 dollars,
and three prospects. Fictional organisations in the association and nonprofit world.

| Account | Type | Tier | ARR (USD) |
|---|---|---|---|
| ACC-0001 Great Lakes Museum Alliance | customer | enterprise | 340,000 |
| ACC-0002 Cascadia Nurses Association | customer | enterprise | 268,000 |
| ACC-0003 Prairie Land Trust Council | customer | professional | 154,000 |
| ACC-0004 Atlantic Shipwrights Guild | customer | professional | 96,000 |
| ACC-0005 Sunbelt Literacy Network | customer | standard | 41,000 |
| ACC-0006 Copper Ridge Youth Foundation | customer | standard | 18,000 |
| ACC-0007 Northwoods Arborists Society | prospect | prospect | 0 |
| ACC-0008 Harbor City Teachers Collective | prospect | prospect | 0 |
| ACC-0009 Silver Creek Veterinary Association | prospect | prospect | 0 |

Nine planted themes. Each generated call or case carries exactly ONE planted theme, so the
arithmetic is exact. A generator may add off topic small talk; it may not plant a second
extractable claim.

| Theme key | Area | W37 calls / cases | W38 calls / cases | W39 calls / cases |
|---|---|---|---|---|
| `renewal_invoice_credit` | membership | 2 / 1 | 1 / 1 | 1 / 0 |
| `event_checkin_kiosk` | events | 2 / 1 | 1 / 1 | 1 / 0 |
| `lms_scorm_support` | lms | 1 / 0 | 1 / 0 | 1 / 0 |
| `dues_notice_deliverability` | integrations | 2 / 2 | 0 / 0 | 0 / 0 |
| `reporting_export_limits` | reporting | 3 / 2 | 2 / 1 | 1 / 1 |
| `accounting_gl_sync` | accounting | 1 / 2 | 1 / 1 | 1 / 1 |
| `job_board_posting_expiry` | jobs | 1 / 1 | 0 / 1 | 0 / 1 |
| `fundraising_pledge_reminders` | fundraising | 2 / 2 | 1 / 1 | 1 / 1 |
| `sso_provisioning_gaps` | integrations | 0 / 0 | 2 / 1 | 1 / 1 |
| **Totals** | | **14 / 11** | **9 / 7** | **7 / 5** |

Which gives the three weeks their jobs:

- **W37** is cold start. Eight themes open from an empty store. All four traps land here.
- **W38** appends to seven of them and opens exactly one new theme,
  `sso_provisioning_gaps`. Nothing else is new, so an agent that opens a second theme has
  failed the append versus open test.
- **W39** gives `dues_notice_deliverability` nothing for a second week running. Its newest
  evidence is from W37, which is more than fourteen days before the 2026-09-28 build, so it
  goes `quiet` and the stale flag fires on a real theme rather than in a unit test. It is the
  only theme that does.

Seven trap files, all in W37, all hand written, all under `data/mock/traps/`:

| Trap | File | Account | Theme | Proves |
|---|---|---|---|---|
| T1a | `traps/gong/calls/7782934451002.json` | ACC-0001 | renewal_invoice_credit | Customer A's wording |
| T1b | `traps/salesforce/cases/5008W00002aQpLrQAK.json` | ACC-0003 | renewal_invoice_credit | Customer B's completely different wording, plus the T4(a) private comment |
| T2a | `traps/gong/calls/7782934451118.json` | ACC-0002 | event_checkin_kiosk | "event check-in" |
| T2b | `traps/gong/calls/7782934451207.json` | ACC-0004 | event_checkin_kiosk | "attendee kiosk" |
| T3 | `traps/gong/calls/7782934451311.json` | ACC-0007 | lms_scorm_support | A prospect asking for SCORM |
| T4b | `traps/gong/calls/7782934451404.json` | ACC-0005 | fundraising_pledge_reminders | An email address, a phone number and a donor name in one turn |
| T4c | `traps/gong/calls/7782934451119.json` | ACC-0006 | reporting_export_limits | A Momentive Software account executive saying a lot of customers ask for this |

T4(a) is a comment inside T1b rather than a file of its own, because the point of it is that
the private comment sits in the same case as the public one and still never reaches the
agent. The generator produces 14 minus 6 = 8 Gong calls and 11 minus 1 = 10 cases in W37;
the trap author writes the other seven files.

## 14. Fixed stage names

`connect`, `scrub`, `extract`, `verify`, `enrich`, `edit`, `score`, `render`, `store`,
`propose`.

Every `AuditEvent` carries one. Every cost table row is keyed by one. Nothing else is a
stage, and no code invents a new one.
