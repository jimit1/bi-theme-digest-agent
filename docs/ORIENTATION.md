# Orientation: what you have and how to run it

This is for you, not for Momentive Software. It is a 45 minute self guided tour of the prototype you designed and a fanout of agents built. Read it with a terminal open at the root of this repository, with the store beside it at `../bi-theme-digest-store`.

## Ten minutes to see it run

Three commands.

```
make setup
make demo
open ../bi-theme-digest-store-demo/digests/2026-W37.html
```

`make demo` took 19.5 seconds when I ran it just now. It clones the store's first commit into a scratch store next door, restores the recorded model responses, replays fifteen nightly ingests and three weekly builds into it, then runs the golden set. Real output from that run: fifteen ingest lines, every one reading `0 rejected (none)`; `build 2026-W37: 0 themes appended, 10 opened`, then W38 with 7 appended and 1 opened, then W39 with 8 appended, 0 opened, 3 quiet and 3 stale; `eval: 18 of 18 assertions passed`; and 19 commits in the scratch store ending at the scaffold commit `b48ad65`. The committed store beside it is only read.

In the HTML page, two things are clickable. Click any evidence line and it expands in place to the source moment: the call or case comment, the speaker, and the quoted sentence highlighted inside the sentences around it. Click **Why this score** under a theme and it expands to five weighted terms with the arithmetic shown, ending in the score printed at the top.

Then open [`../bi-theme-digest-store-demo/digests/2026-W37.md`](../../bi-theme-digest-store-demo/digests/2026-W37.md) and read three things: the run line at the top (25 sources read, 4 private comments withheld, 5 PII redactions, 27 claims verified, 0 rejected, cost $2.27 for the week), the cold start paragraph, and theme 1 with its three evidence lines and its claim ids in square brackets.

## The map

Top level of the code repository:

- [`src/digest/`](../src/digest) the package, everything that runs.
- [`contracts/`](../contracts) the schema pack. Every boundary validates against a file here. This is the law.
- [`mcp/`](../mcp) the two mock MCP servers, Gong and Salesforce, that enforce read only access at the boundary.
- [`config/`](../config) `models.yaml` and `models.cheap.yaml`, the only runtime files that name a model, plus the build tier maps.
- [`data/mock/`](../data/mock) the generated corpus, the four hand written traps, the account file and the PII name list.
- [`tests/`](../tests) 531 tests, one file per area, plus fixtures.
- [`evals/`](../evals) the golden set and its recorded results.
- [`docs/`](../docs) decisions, governance, cost, production context, future builds, the verification guide, this file.
- [`deck/`](../deck) the review deck, its outline, and seventeen rendered panels under `assets/`.
- [`tools/`](../tools) the corpus generator.
- [`.claude/`](../.claude) the same agent roles as Claude Code subagents, plus a digest skill.
- [`.github/workflows/`](../.github/workflows) the nightly ingest and weekly digest crons.

Every file under `src/digest`, one line each:

`__init__.py` package docstring. `__main__.py` the CLI, eight verbs. `pipeline.py` the glue that runs a day, a week and the demo. `router.py` the model seam: tier to model, capability negotiation, validate then retry once, cost, record and replay. `store.py` the only module that writes to the store repository. `audit.py` one validated AuditEvent per line per run. `contracts.py` loads and enforces the schema pack. `errors.py` every exception and its exit code. `verify.py` schema validation and citation verification. `enrich.py` deterministic per account tier, ARR, open cases, renewal. `score.py` the five term score, no model. `eval.py` the golden set, run mechanically. `swap.py` rerun a week on another tier map and print the comparison. `gate.py` the human approval gate, the only path that reaches outside the store.

`connectors/base.py` the `SourceConnector` protocol. `connectors/gong.py` calls in, one SourceDocument out. `connectors/salesforce.py` cases in, private comments already absent. `connectors/mcp_client.py` a synchronous MCP stdio client.

`pii/scrubber.py` four regex passes, email, phone, address, name, before any model call.

`providers/__init__.py` the provider protocol. `providers/_families.py` per family thinking and effort rules. `providers/agent_sdk_seat.py` the working default, the `claude` CLI on a seat. `providers/anthropic_direct.py` implemented, tested against a captured request body. `providers/bedrock.py`, `vertex.py`, `foundry.py`, `openai_compatible.py` honest stubs with real model id translation.

`agents/readers/reader.py` one scrubbed document in, one ReaderOutput out. `agents/readers/gong_reader.prompt.md` and `sfdc_reader.prompt.md` the two extraction prompts, version 1.2.0. `agents/editor/editor.py` the two call editor. `agents/editor/tools.py` the four read only tools and no write tool. `agents/editor/theme_request.prompt.md` call one. `agents/editor/editor.prompt.md` call two. `agents/analyst/analyst.py` one question, one grounded answer. `agents/analyst/retrieval.py` keyword search over the theme store. `agents/analyst/analyst.prompt.md` the analyst prompt.

`render/markdown.py` the markdown digest. `render/html.py` the single file HTML digest, inline CSS and script, no network. `render/citations.py` the citation label and the source moment it expands to. `render/scoring.py` re-derives the score arithmetic for display.

## The pipeline in your own words

Nine stages. Eight are code. One is a model asked for judgment.

1. **Connect.** [`src/digest/connectors/`](../src/digest/connectors) through [`mcp/`](../mcp). No model. The window, the field allowlist, the row cap and `IsPublished = true` are enforced here, not in a prompt.
2. **Scrub.** [`src/digest/pii/scrubber.py`](../src/digest/pii/scrubber.py). No model. Nothing is persisted unscrubbed, because `SourceDocument.scrubbed` is `const: true`.
3. **Extract.** [`src/digest/agents/readers/reader.py`](../src/digest/agents/readers/reader.py), tier `extraction`, `claude-haiku-4-5`. Prompts: [`gong_reader.prompt.md`](../src/digest/agents/readers/gong_reader.prompt.md) and [`sfdc_reader.prompt.md`](../src/digest/agents/readers/sfdc_reader.prompt.md).
4. **Validate and verify.** [`src/digest/verify.py`](../src/digest/verify.py). No model. The quote must be an exact substring of the cited turn or the claim is rejected. Never patched.
5. **Enrich.** [`src/digest/enrich.py`](../src/digest/enrich.py). No model. Joins and arithmetic.
6. **Edit.** [`src/digest/agents/editor/editor.py`](../src/digest/agents/editor/editor.py), tier `synthesis`, `claude-opus-5`. Two calls: [`theme_request.prompt.md`](../src/digest/agents/editor/theme_request.prompt.md) names the themes it needs, code opens and logs them, then [`editor.prompt.md`](../src/digest/agents/editor/editor.prompt.md) returns the proposal.
7. **Score.** [`src/digest/score.py`](../src/digest/score.py). No model. The editor writes the rationale, code computes the number.
8. **Write and commit.** [`src/digest/store.py`](../src/digest/store.py) and [`src/digest/render/`](../src/digest/render), logged by [`src/digest/audit.py`](../src/digest/audit.py). No model.
9. **Gate.** [`src/digest/gate.py`](../src/digest/gate.py). No model. Nothing is filed without a human typing `--yes`.

Off to the side, `make ask` runs [`src/digest/agents/analyst/analyst.py`](../src/digest/agents/analyst/analyst.py) on tier `narrative`, `claude-opus-5`, over the theme store only.

## The store

[`../bi-theme-digest-store`](../../bi-theme-digest-store) is a second repository with no code in it.

- `ROUTER.md` layer 0, under 5KB, always read first.
- `themes/_INDEX.md` layer 1, one table row per theme: id, title, product area, status, score, account count, evidence count, last updated run, aliases. Regenerated from the theme files on every write, so it cannot drift.
- `themes/THEME-nnnn.md` layer 2. Open [`THEME-0002.md`](../../bi-theme-digest-store/themes/THEME-0002.md): frontmatter carries the aliases, the accounts, the evidence claim ids, the score and its seven inputs; the body carries a "Why this matters" paragraph and an evidence table with one row per claim, each with its account, source, moment and verbatim.
- `sources/` the scrubbed source documents. `sources/_INDEX.md` frontmatter holds the watermark, `last_ingest_run` and `last_ingest_day`, which is why a nightly run never re-reads the corpus.
- `evidence/claims/<run_id>.jsonl` one verified claim per line. `evidence/rejected/` empty, which is the point.
- `runs/<run_id>/` per run: `run.log.jsonl`, `manifest.json`, `week_summary.json` and the recorded responses.
- `digests/` and `proposals/` the outputs a person reads.

One audit line, in full, is the shape of the control:

```
{"ts": "...", "run_id": "2026-09-21T06:00Z", "agent": "scrubber", "action": "scrub", "target": "500000000000000016", "model_tier": null, "tokens_in": 0, "cost_usd": 0.0, "outcome": "ok", "detail": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}}
```

Counts, never values. Reads are logged as well as writes. Above that, `git log` in the store is the audit trail at run level: one commit per pipeline run, 26 in the committed store today, which is the 23 the README quotes plus the three later `ask` and `approve` runs.

## How to change something

**Change a prompt.** Edit the prompt file and bump `prompt_version` in its frontmatter. Then understand what you broke: the replay key is `sha256(tier, system, user, schema_name)`, so changing a prompt invalidates every committed recording for that agent and `make demo` stops with exit 3, a replay miss. It never falls back to a live call. Regenerating means `python -m digest demo --mode record`, which is about 54 minutes and real money.

**Change a tier.** Edit [`config/models.yaml`](../config/models.yaml). That is the only runtime file naming a model. The replay key uses the tier name, not the model id, so replay will happily hand you the old model's answer. To actually compare models, use `make swap-models`, which records the alternate side into its own `responses-swap` directory and prints three lines: cost, eval pass rate, and claim co-assignment overlap.

**Add a source.** One file in [`src/digest/connectors/`](../src/digest/connectors) implementing `list_since` and `fetch`, plus a config entry. No pipeline branch.

**Tests.** [`tests/`](../tests), one file per area. Run one file with `.venv/bin/python -m pytest tests/test_score.py -q`. That one takes 0.15 seconds and passes 11 tests. `make test` runs all 531.

## How it was built

Six waves under one orchestrator, thirty briefs. Wave 0 was the contract pack alone, because fourteen later workers had to build in parallel without talking. Waves 1 and 2 were seven workers each, wave 3 the pipeline, wave 4 the docs, wave 5 the QA auditors, wave 6 the deck. Every worker owned an exclusive set of paths, read only the contract slices its brief named, and returned a JSON envelope with a mandatory `assumptions` array. [`build/briefs/B1.md`](../../build/briefs/B1.md) shows how narrow a brief was; [`build/envelopes/B16.json`](../../build/envelopes/B16.json) shows what came back, including the three live runs.

The tuning story is the part worth telling. Run 1 produced 83 claims and 20 themes against a plan of nine, the golden set came back 17 of 18, and rerunning week 37 agreed with itself at 0.79 Jaccard. Three causes, each fixed at its owner: filler conversation in the generated corpus carried extractable asks, the readers split one point into a problem claim and a fix claim, and the editor split facets of one problem into separate themes. Run 2 gave 55 claims and 12 themes, Jaccard 1.000, but the golden set still caught one reader recall miss, so the reader prompts went to 1.2.0 with a recall first rule and a stricter praise test. Run 3 is what is committed: 55 claims from 53 sources, 11 themes, 18 of 18, zero rejected, $5.47 by the rate table.

The QA wave built nothing and each auditor caught something. The acceptance auditor found `make demo` failing on a fresh clone because the weekly build was not idempotent; that produced the already built guard and the scratch store demo. The citation auditor resolved all 55 claims and all 125 digest evidence lines by hand with its own throwaway resolver and caught the doubled PII redaction count, which was the real bug. The compliance auditor found a local home directory path leaking into `evals/results.md`. The deck auditor traced every number on every slide and failed the deck on a stale whole store total, with a numbered fix list, all of which is now in.

## Known gaps and honest caveats

- One sentence in the W37 digest calls a claim "the one medium-importance claim in the set" when there are two. Left in rather than hand editing a recorded run's output. It is the only unbacked assertion in 125 evidence lines.
- Week 37 opened ten themes where the plan expected nine. The extra one is real, cited, and no assertion objects. Tuning it away would have been tuning to your plan rather than to the evidence.
- The stability number is honest and awkward. Two live opinions on W37 grouped every claim identically, Jaccard 1.000, but the older flag compared theme ids and read false, because ids are handed out in the editor's placeholder order. Both numbers are printed.
- Three acceptance lines are untestable locally: live mode, a real issue being filed, and the deck audit.
- The citation auditor could not reproduce the dollar figures by hand, because nothing in the store carries a price.
- `evals/golden_set.yaml` carries the raw planted PII values in a public facing file. Functionally correct, worth a second opinion.
- The manifest counts propose events, so the weekly manifests read 13, 11 and 9 while the proposal directories hold 6, 5 and 4. Both are published.
- `make approve` carries `--yes` already and defaults to a real repository. Never run it to show what the gate does.

## How to demo it live in ten minutes

This matches [`walkthrough.md`](../walkthrough.md), stretched from three minutes to ten.

1. `make demo`. Say: fifteen nightly ingests and three weekly builds, replayed from recorded responses, twenty seconds, zero network, byte identical to what is committed.
2. Open `../bi-theme-digest-store/digests/2026-W37.md`. Read the run line, then theme 1.
3. `grep 03a7ca4ae6d8 ../bi-theme-digest-store/evidence/claims/2026-09-08T06:00Z.jsonl | python -m json.tool`. Point at `source_ref`: call, speaker, window, and `speaker_side` derived by code.
4. `grep -c "Every renewal statement we send out is missing the balance" data/mock/traps/gong/calls/7782934451002.json`. Say the rule once: the quote is an exact substring of that window or the claim is rejected.
5. `grep '"action": "withhold"' ../bi-theme-digest-store/runs/2026-09-10T06:00Z/run.log.jsonl`. The withholding happened in the query. The log has the count and never the value.
6. `grep -n "def read_theme_index\|def read_theme\|def list_run_claims\|def read_account\|def write" src/digest/agents/editor/tools.py`. Four reads. `def write` matches nothing.
7. `python -m digest approve --theme THEME-0002 --dry-run --mode replay --repo OWNER/product-feedback`, then the same without `--dry-run`. Exits 4, refused. Close on: the agent decided what was worth filing, a person files it.
8. If there is time, `make swap-models` and `make ask Q="how many seats does the mobile app licence include next year"` to show the decline.

## How to record the Loom

Terminal at a large font, nothing else on screen, browser ready on the HTML digest in a second tab. Run `make demo` once before you hit record so the interpreter caches are warm and the scratch store exists. Do not narrate the setup. Start on the first command already typed and unexecuted. Keep to the eight beats above, one take, and put the recording location into the line at the top of [`walkthrough.md`](../walkthrough.md) afterwards.

## Before Momentive tests it

- `make test` reads 531 passed.
- `make demo` from a clean tree reads 18 of 18 and 19 commits.
- `git status --porcelain` is empty in both repositories.
- The store is at its committed state. `make clean-store` if not.
- `grep -rlP '[\x{2013}\x{2014}]' --exclude-dir=.git --exclude-dir=.venv .` prints nothing.
- The home directory path in `evals/results.md` is gone before these repositories go public.
- [`docs/VERIFY.md`](VERIFY.md) is the page you send. It is the one that tells a stranger what to type and what should come back.
