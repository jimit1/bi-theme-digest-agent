# Scaffold for `ROUTER.md` in the store repository

Copy the block below verbatim into `bi-theme-digest-store/ROUTER.md`. It is layer 0 of the
context store: always loaded, under 5KB, and the first thing any agent reads. Nothing below
the horizontal rule is commentary; it is the file.

---

```markdown
---
schema_version: "1.0.0"
owner: ai-operations
source: pipeline
last_verified: 2026-09-14
run_id: 2026-09-14T07:00Z
---

# ROUTER

You are reading the context store of the BI theme-digest agent, built for Momentive Software.
This file is layer 0. It is always loaded and it is under 5KB on purpose. Read it before you
read anything else in this repository.

## What this repository is

Everything the agent has learned about what clients are saying, kept between runs so it is
not regenerated every time. It contains no code. Its git history contains nothing but
pipeline commits, which is what makes `git log` here an audit trail rather than a changelog.

Three layers, read in order, and you stop as soon as you have enough:

| Layer | Path | When you read it |
|---|---|---|
| 0 | `ROUTER.md` | Always. This file |
| 1 | `themes/_INDEX.md` | Always. One line per theme: id, title, product area, status, score, counts, last run, aliases |
| 2 | `themes/THEME-nnnn.md` | Only the themes layer 1 told you are relevant |

Reading the whole theme directory is a mistake, not a shortcut. Layer 1 exists so you do not
have to, and because layer 2 can be gated by role, progressive disclosure here is also least
privilege by construction.

## What else is here

| Path | What it holds |
|---|---|
| `evidence/claims/<run_id>.jsonl` | Every verified claim, append only |
| `evidence/rejected/<run_id>.jsonl` | Every rejected claim with its reason code |
| `sources/_INDEX.md` | One line per ingested call and case, and the ingestion watermark |
| `sources/<source_id>.json` | The scrubbed source document, exactly as a reader agent saw it |
| `proposals/<week>/<theme_id>.md` | What the editor proposed for filing, sitting unapproved |
| `digests/<week>.md` and `.html` | The weekly digest a product manager reads |
| `runs/<run_id>/run.log.jsonl` | Every agent action including reads, with tokens and cost |
| `runs/<run_id>/manifest.json` | End of run counts, cost by stage and tier, stability |
| `runs/<run_id>/responses/` | Recorded model responses, so any run can be replayed |

## What you may read

All of it. Everything here has already been through the PII scrubber, which is why this
repository can be public.

## What you may never write

Nothing, if you are a model. Every write in this repository is performed by pipeline code
after that code has validated a document against a schema in `contracts/`. No agent in this
system has a write tool. That is not a policy, it is an absence: there is no tool to call.

If you are a person: edit by hand only when you mean to break the audit trail, and say so in
the commit message.

## The hard rules

1. **Every claim carries its source moment.** A claim's `verbatim` is an exact substring of
   the cited turn, checked in code before the claim enters this repository. A claim whose
   citation does not resolve is rejected and logged, never patched.
2. **Only client claims live here.** A Momentive Software employee saying "a lot of our
   customers ask for this" is not a client claim, and the verifier rejects it with
   `speaker_not_client`.
3. **Nothing internal ever arrived.** Private Salesforce comments are excluded by the SOQL
   query, not filtered afterwards, so they were never in the result set. The count that was
   withheld is in the run log as a number.
4. **Nothing here is raw.** Email addresses, phone numbers, street addresses and donor names
   were replaced with placeholders before any model call. The run log records counts, never
   values.
5. **Scores are arithmetic, not judgment.** The seven inputs are stored on every theme so a
   reviewer can recompute the number. The model writes the rationale and never the score.
6. **The verify horizon is fourteen days.** A theme whose `last_verified` is older than that
   is flagged `stale`, and any agent reading it says so rather than quoting it as current.
7. **Filing is a human action.** The agent proposes; a person runs `approve --yes`. A
   proposal sitting in `proposals/` has not been filed anywhere.

## If you are answering a question from this store

Answer only from what is here, cite the theme and the claim, and if the store does not
support the answer, say that instead of guessing. An unsupported answer with no citations and
a stated reason is a correct answer. A confident one without evidence is not.
```
