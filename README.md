# BI theme digest agent

I built this for Momentive Software. It reads a day of Gong call transcripts and Salesforce support case threads, extracts every client claim with the exact moment it came from, verifies each citation resolves to real source text before anything else happens, and merges the claims into a theme store that persists between runs instead of being regenerated each week. The output is a weekly digest a product manager can read in five minutes where every sentence is one lookup from the transcript second or case comment that produced it, and nothing reaches a system of record without a person running an explicit approve command.

## How to run it in sixty seconds

Clone two repositories side by side into one parent directory: the code, the bi-theme-digest-agent repository under the jimit1 account, and the context store, the bi-theme-digest-store repository under the same account. The store has to sit beside the code as `../bi-theme-digest-store`, which is the default every command uses. Run `make setup` once, then:

```
make demo
```

That is a full replay of three weeks from an empty store: about twenty seconds, no network, no API key. It clones the store's first commit, the empty scaffold, into `../bi-theme-digest-store-demo`, puts the recorded model responses back, runs the fifteen nightly ingests and the three weekly builds into that scratch store, then runs the golden set against what came out. It prints the three digest paths, the nineteen commits the pipeline made one per run, and `18 of 18 assertions passed`. The committed store beside it is only read, never written, and it already holds the same digests, themes and evidence byte for byte. The HTML digest is a plain file: `open ../bi-theme-digest-store-demo/digests/2026-W37.html` on macOS opens it straight from the filesystem in your default browser, no server involved.

`make demo-inplace` runs the same pipeline against the committed store at `../bi-theme-digest-store` instead, where every ingest day is behind the watermark and every week is already built, so every step reports itself as already done and nothing is rewritten, which is what a store that persists between runs is for. `make clean-store` puts that store back if anything ever does write to it.

```
make demo-live     # the same run live: about 54 minutes, $4.26 by the rate table
make eval          # the golden set, 18 assertions, the exit code is the result
make ask Q="why does the renewal invoice credit issue matter"
make approve THEME=THEME-0002
make swap-models   # rebuild week 2026-W37 on the cheap tier map and compare
make test          # 531 tests
```

`make ask` answers from the theme store only, with no access to the sources, and when the store does not support an answer it says so instead of guessing. `make approve` is the human gate: it passes `--yes` and `--repo` for you, the repository being `REPO=owner/name` if you want a different one, and the command exits 4 without `--yes`. Add `--dry-run` to print the issue and file nothing.

## Architecture

```
  nightly (cron)                                         weekly (cron)
  --------------                                         -------------

  [1] connectors       [2] scrub           [3] extract          [4] validate
  gong_mcp     ---+                        gong_reader          schema check (code)
                  +-> pii_scrubber     --> sfdc_reader      --> citation verify (code)
  sfdc_mcp     ---+   (code, pre-model)    (extraction tier)    reject, never patch
  read-only, scoped                                                    |
                                                                       v
                                                [5] enrich (code, no model)
                                                tier, ARR, open cases, renewal
                                                                       |
                                                                       v
                                  [6] EDITOR AGENT (synthesis tier, the primary)
                                      reads the theme index FIRST, then decides per
                                      claim: append to an existing theme or open a
                                      new one, and says why. Writes the digest.
                                      Proposes what to file. Four read-only tools.
                                      No write tool exists for it to call.
                                                                       |
                                  [7] score in code, rationale from the editor
                                                                       |
                                                                       v
                                  [8] code writes the store  --> commit to store repo
                                                                       |
                                  -------------------------------------+-------------
                                  |                      |                          |
                             digest.md             digest.html              ask (CLI)
                                  |                                      (narrative tier)
                                  v
                             [9] HUMAN GATE: approve --theme THEME-0002 --yes
                                  |
                                  v
                             GitHub issue filed
```

Application code asks for a tier, never for a model. `config/models.yaml` is the only runtime file that names one: extraction is `claude-haiku-4-5`, synthesis and narrative are `claude-opus-5`. Swapping the map is one file, which is what `make swap-models` does.

## The traceability guarantee

The rule: a sentence reaches the digest only if it carries a claim id, and a claim exists only if its `verbatim` is an exact substring of the source span it cites. Code asserts that substring, not the model. A claim whose citation does not resolve is rejected with a reason code, logged, and never enters the store. Never patched, never coerced.

One worked example, real values throughout. The 2026-W37 digest says:

> Great Lakes Museum Alliance says every renewal statement it sends is missing the balance carried over from the previous period, so the invoice total reads far higher than it should; they have worked around it since the spring and the board has now noticed.

The evidence line under that theme carries claim `03a7ca4ae6d8`, call `7782934451002` at 11:03, Rhonda Calloway. The claim record sits in `../bi-theme-digest-store/evidence/claims/2026-09-08T06:00Z.jsonl` and cites speaker 4521 in the window 663288 ms to 722760 ms, which is one turn of `data/mock/traps/gong/calls/7782934451002.json`. The sentence at 681342 ms in that file reads, exactly: "Every renewal statement we send out is missing the balance that carried over from the previous period, so the invoice total reads far higher than it should." 663288 ms is the 11:03 the digest prints. All 55 claims and all 125 digest evidence lines resolve this way.

## Who does what

Code owns sequencing, validation, citation checking, scoring arithmetic and every write, because those have to give the same answer twice. The editor owns judgment: whether two differently worded complaints are the same theme, when something genuinely new has appeared, and why a product manager should care. An agent that also controlled sequencing would make week over week stability a function of model sampling, which is the drift I was asked about, and an agent with a write tool would make the approval gate advisory. So the editor has neither and loses nothing it was good at. It decides what is worth filing and writes the proposal; `approve` files, when a person runs it.

Three more, one line each. The store is a separate repository with no code in it, so its `git log` is an audit trail rather than a changelog: 23 commits, one per pipeline run. Ingestion never re-reads the corpus, because `sources/_INDEX.md` carries `last_ingest_run` and `last_ingest_day` as a watermark and each night pulls only what is newer. The build itself ran behind a two agent gate where whoever wrote a piece never checked it, and the citation audit is what caught the redaction count bug below.

## The docs

- `docs/PRODUCTION_CONTEXT.md`: how the agent gathers its own context in production. Schedule, incremental pull, MCP connectors as the production swap, scoped credentials, the store as memory, drift, the gate.
- `docs/GOVERNANCE.md`: seven controls, each with the command that demonstrates it, plus the NIST AI RMF mapping.
- `docs/COST_AND_KPIS.md`: four cost numbers and four KPIs from the real run.
- `docs/metrics/cost_table.md`: the measured tables, regenerated from the committed audit logs by `recompute.py`.
- `docs/DECISIONS.md`: the numbered decision log, including the Bedrock answer.
- `docs/FUTURE_BUILDS.md`: nine items, ordered, each with what it needs to be safe. None of it is built.
- `evals/results.md`: the golden set run, per assertion, with the grep commands and their output.
- `walkthrough.md`: the four beats of the recording, with the command for each.
- `docs/VERIFY.md`: the independent verification guide, from an empty clone to every number above, with the exact expected output for each step.

## The numbers

- Cost of the sample run: $2.27 for week 2026-W37, of which $1.22 is the build and the rest five nightly ingests. Three weeks plus the analyst runs, now three of them, come to $5.07 by the rate table, and the whole live build cost $5.47 by the table, $6.69 by the CLI's own accounting, which bills a cache write higher. Source: `docs/metrics/cost_table.md`, sections 1 and 5.
- Claims: 55 verified, 0 rejected, from 53 source documents, all five rejection reasons at zero. 10 private case comments withheld at the query, 5 PII values redacted before any model saw them. Source: `docs/metrics/cost_table.md` section 5 and each digest's run line.
- Themes: 11 by week 2026-W39. Ten opened in W37, exactly one in W38, none in W39, three quiet and three stale. Source: `../bi-theme-digest-store/themes/_INDEX.md`.
- Eval: 18 of 18 assertions pass, exit 0, in replay. Source: `evals/results.md`.
- Stability: two live opinions on W37 grouped the week's claims identically (claim co-assignment Jaccard 1.000) and put the same three themes on top in the same order. The older flag compared allocated theme ids and read false; both are printed, because ids are handed out in the editor's placeholder order, which on a cold start week measures the labelling rather than the ranking. Source: `evals/results.md` and `docs/metrics/cost_table.md` section 7.

## How the build went

The first live run was measured and not shipped: 83 claims and 20 themes against a plan of nine, eval 17 of 18, a W37 rerun agreeing on 0.79 of its claim groupings. Three causes, each fixed at its owner and re-run end to end: filler conversation in the generated corpus carried extractable asks, the readers split one point into a problem claim and a fix claim and quoted restatements, and the editor split facets of one problem into separate themes. The final run is what is committed, with the eval at 18 of 18 and an independent citation audit as the proof rather than my say so. That audit raised two soft findings. One was real: the digest reported 10 PII redactions where 5 values were planted, because the scrubber counted the turn text and the per sentence copies of it. The redaction was right, the count was doubled, and it is fixed and the store regenerated. The other stands: one sentence in the W37 digest calls a claim "the one medium-importance claim in the set" when there are two, and I left it rather than hand edit a recorded run's output.

## What I cut, and why

- Real Gong and Salesforce API integration. The brief said mock, and the MCP boundary is the seam that makes the swap a credential change.
- A web UI or a hosted service. The digest is a file and a page, because that is what a product team actually reads.
- Authentication, multi-tenancy and RBAC on the store. Git permissions are the prototype's access control.
- The adaptive eval agent that updates other agents' context. It is the right next stage and belongs behind the same gate, so it is designed in `docs/FUTURE_BUILDS.md` and not built.
- Vector retrieval. At this corpus size the theme index is smaller and more auditable than an embedding store. When it stops fitting comfortably in layer one, retrieval goes behind a tool with citations required.
- Slack or Teams delivery. One connector, no new thinking, not worth the hours.

Jim Mehta, jimit1@gmail.com.
