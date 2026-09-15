# Deck outline: BI theme digest agent

This is the slide plan for `deck/momentive-bi-digest.pptx`. Twenty two slides, 16:9, built to
be read cold by someone who has never met me. Every slide below carries the sentences that go
on it, the asset it uses, the speaker notes, and a `numbers:` list that maps every figure on
the slide back to a manifest field. A number that is not in that list does not go on a slide.

## Where the numbers come from

Five manifests plus two audit envelopes. The short names used in every `numbers:` list below:

| Short name | File | Root path |
|---|---|---|
| `EvalResult` | `build/envelopes/B17.json` | `measured.EvalResult` |
| `MetricsResult` | `build/envelopes/B18.json` | `measured.MetricsResult` |
| `CorpusManifest` | `build/envelopes/B2.json` | `measured.CorpusManifest` |
| `IntegrationManifest` | `build/envelopes/B16.json` | `measured.IntegrationManifest` |
| `AcceptanceReport` | `build/envelopes/B24.json` | `measured.AcceptanceReport` |
| `CitationAudit` | `build/envelopes/B25.json` | `measured.CitationAudit` |
| `ComplianceReport` | `build/envelopes/B26.json` | `measured.ComplianceReport` |

Two corrections are already folded in and both are named where they appear. The PII redaction
total is five, not ten: `IntegrationManifest.corpus.pii_redactions` still carries the doubled
count from before the scrubber fix, and the corrected value is
`B16.consolidation.what_actually_differs.scrub_counts` and the W37 digest run line. The top
three stability flag is true by claim set and false by allocated theme id:
`IntegrationManifest.stability_w37_live.top3_stable` carries the old id comparison and
`B16.consolidation.stability_result` carries both.

## Design

One dark ink colour, `#1F2933`. One accent, `#2F5D8C`. One muted grey for captions,
`#6B7785`. Body type is Calibri with Arial as the fallback, both system safe. No logos, no
company marks of any kind, mine or theirs. Title slide carries the title, one line saying
what it is, my name and the date, and nothing else.

---

## 1. Title

Sentences on the slide:

- BI theme digest agent
- An agent that turns a week of client calls and support cases into a themed digest where every sentence traces back to the second it was said.
- Jim Mehta
- 2026-09-16

Asset: none.

Speaker notes: This is a working prototype, not a concept deck. Two public repositories, one
for the code and one for the context store it writes to. Everything in this deck can be run
from a clone with no API key and no network, because every model response from the sample run
is committed. I will point at a file, a command or a manifest on every slide, and if I cannot
point at one I have cut the slide.

numbers: none on this slide.

---

## 2. The brief, restated

Sentences on the slide:

- The ask: build an agent that reads what clients are telling us across calls and support cases, and turns it into something a product team can act on every week.
- Three things had to be true, and each one drove a design decision rather than a paragraph.
- Every claim traceable to its moment. A sentence reaches the digest only if it carries a claim id, and a claim exists only if its quoted text is an exact substring of the source span it cites. Code asserts that substring, not the model.
- Context that persists between runs. The themes live in their own repository and are appended to, not regenerated, so week three costs less than week one and the store is the memory.
- An agent whose access is bounded. The agent that holds the most context has four read-only tools and no write tool exists for it to call.
- The measurable version of the first: 55 claims verified, 0 rejected, 55 of 55 citations resolved.

Asset: none. This slide is prose on purpose.

Speaker notes: I restate the brief in my own words first, because the three constraints I
pulled out of it are the ones I want to be graded on. Traceability is the one I would defend
hardest. It is cheap to produce a plausible weekly summary with a language model and
expensive to produce one a product manager will still believe in six weeks. The other two
follow from it: if the store is regenerated every week the digest drifts, and if the agent can
write then the approval gate is advice rather than a control.

numbers:

- 55 claims verified: `MetricsResult.three_week_totals.claims_verified`
- 0 rejected: `MetricsResult.three_week_totals.claims_rejected`
- 55 of 55 citations resolved: `EvalResult.per_assertion.S1` and `CitationAudit.full_sweep_claims_resolved`

---

## 3. What it does

Sentences on the slide:

- Nine stages. Code runs eight of them, and one model agent runs the ninth.
- Nightly: the connectors pull the previous day, the scrubber removes PII before any model sees a document, two reader agents at the extraction tier pull claims, and code validates the schema and verifies every citation.
- Weekly: code enriches accounts deterministically, the editor agent at the synthesis tier reads the theme index first and decides append or open new, code scores in arithmetic a reviewer can recompute, and code performs every write.
- Then a human gate: nothing reaches a system of record until a person runs approve with an explicit confirmation.
- Tier, not model: application code asks for a tier and `config/models.yaml` is the only runtime file that names a model.

Asset: `pipeline_diagram` from `deck/assets/manifest.json`, the annotated pipeline rendered
from the README architecture block, each stage labelled with the tier that runs it. Caption:
`README.md, architecture section`.

Speaker notes: The shape of this is the argument. Code owns sequencing, validation, citation
checking, scoring arithmetic and every write, because those have to give the same answer
twice. The editor owns judgment, because judgment is what a model is for. An agent that also
controlled sequencing would make week over week stability a function of model sampling, which
is exactly the drift question I was asked. If somebody asks why the readers are a cheap tier,
slide fifteen has the subtraction.

numbers: none on this slide. Tier names and stage count are structural, from
`docs/DECISIONS.md` decisions 12, 13 and 25.

---

## 4. The two sources

Sentences on the slide:

- Gong for calls and Salesforce for support cases, behind two local MCP servers that advertise seven tools between them.
- Gong: call metadata by date range, the participant list that maps a speaker id to a person, and the transcripts.
- Salesforce: SOQL through the REST query endpoint over Case, CaseComment, Account and User.
- Five rules are enforced at the tool boundary, in the tool, not in a prompt. There is no write tool to call, not a disabled one and not a gated one. The date window comes from the launcher and a request outside it is refused rather than trimmed. IsPublished equals true is in the SOQL itself. There is a field allowlist. There is a row cap of 200.
- The agent cannot ask for what it is not allowed to see, because the tool will not form the query.
- The mock serves the real response shapes, cursor pagination included, so production is a base URL and a credential with no translation layer.

Asset: `connector_tools_panel`, a rendered excerpt of the MCP tool definitions showing the
seven tool names and the scoping arguments. Caption: `mcp/salesforce_server.py`.

Speaker notes: This is the slide where an IT reader decides whether to keep listening. The
line I want to land is the last but one. Least privilege written as a prompt instruction is a
hope. Least privilege written as a tool that will not form the query is a control, and there
is nothing to misconfigure because the capability was never registered. The row cap exists so
that a runaway loop cannot pull the corpus, which is a different failure from a malicious one
and more likely.

numbers:

- seven tools: `docs/PRODUCTION_CONTEXT.md`, connector section, enumerated by name
- row cap 200: `docs/GOVERNANCE.md`, cost caps section, `DIGEST_ROW_CAP`

---

## 5. One claim, traced end to end

This is the most important slide in the deck.

Sentences on the slide:

- One sentence in the digest, followed all the way back to the second it was said.
- The digest says Great Lakes Museum Alliance sees every renewal statement missing the balance carried over from the previous period, so the invoice total reads far higher than it should.
- The evidence line under it carries claim 03a7ca4ae6d8, call 7782934451002 at 11:03, Rhonda Calloway.
- The claim record cites speaker 4521 in the window 663288 ms to 722760 ms, which is one turn of the transcript.
- The transcript turn at 681342 ms contains that sentence as an exact substring. 663288 ms is the 11:03 the digest printed.
- All 55 claims and all 125 digest evidence lines resolve this way, and a claim whose citation does not resolve is rejected and logged rather than patched.

Asset: `trace_four_panel`, four stacked panels on one slide: the digest paragraph, the
evidence line, the claim JSON record, and the transcript turn with the quoted span
highlighted. Captions, one per panel:
`../bi-theme-digest-store/digests/2026-W37.md`,
`../bi-theme-digest-store/digests/2026-W37.md, evidence line`,
`../bi-theme-digest-store/evidence/claims/2026-09-08T06:00Z.jsonl`,
`data/mock/traps/gong/calls/7782934451002.json`.

Speaker notes: If they remember one slide it is this one. I walk it top to bottom and say the
quiet part: the substring assertion is done by code, not asserted by the model, so the
traceability claim does not depend on the model behaving. Then the number that makes it a
system rather than an example: 55 of 55, checked by the pipeline's verifier and separately by
a hand audit that did not use that verifier, which is slide nineteen. If asked why citations
resolve to the turn and not the sentence: a model computing millisecond boundaries is exactly
the arithmetic that should not be delegated to a model.

numbers:

- claim 03a7ca4ae6d8 on theme THEME-0002: `EvalResult.per_assertion.T1a`
- 55 claims resolved: `CitationAudit.full_sweep_claims_resolved` and `EvalResult.per_assertion.S1`
- 125 digest evidence lines checked, 0 bad: `CitationAudit.digest_evidence_lines_checked` and `CitationAudit.digest_evidence_lines_bad`
- 0 rejected: `MetricsResult.three_week_totals.claims_rejected`

---

## 6. The context store

Sentences on the slide:

- The store is a separate repository with no code in it, and the pipeline's only write credential reaches it and nothing else.
- Three layers, read in order, and the reader stops as soon as it has enough. Layer 0 is a router file under five kilobytes. Layer 1 is the theme index, one line per theme. Layer 2 is an individual theme file, opened only when the index says that theme is relevant.
- Progressive disclosure is also least privilege here, because layer 2 can be gated by role.
- Every commit is made by pipeline code after that code validated a document against a schema, so git log is an audit trail rather than a changelog: 23 commits, one per pipeline run.
- The store is why the digest is not rebuilt from scratch. Week 37 opened 10 themes into an empty store. Week 38 appended 7 and opened exactly 1. Week 39 appended 8 and opened 0.

Asset: `store_git_log_panel`, real captured output of git log in the store repository showing
ingest, build, stability, swap, ask and approve commits and nothing else. Caption:
`$ git -C ../bi-theme-digest-store log --oneline`.

Speaker notes: Two repositories is a decision I would defend in a design review. The audit
argument is the one I lead with, because a git log that mixes pipeline commits with code
changes answers no question anyone actually asks. The blast radius argument is the second:
the store holds no secrets and no code, so a compromised agent credential reaches one
repository that contains nothing worth taking. The append versus open numbers on the bottom
line are the store behaving as memory, and the cost consequence is on slide fifteen.

numbers:

- 23 commits: `IntegrationManifest.corpus.store_commits`
- W37 appended 0, opened 10: `MetricsResult.three_week_totals` per week block, `2026-W37`
- W38 appended 7, opened 1: `IntegrationManifest.builds[1].appended` and `.opened`
- W39 appended 8, opened 0: `IntegrationManifest.builds[2].appended` and `.opened`

---

## 7. Two customers, one theme

Sentences on the slide:

- Trap T1 in the mock corpus: two customers describe the same billing failure in vocabulary that shares almost no words, and they have to land on one theme.
- Great Lakes Museum Alliance, on a call: every renewal statement is missing the balance that carried over from the previous period, so the invoice total reads far higher than it should.
- Prairie Land Trust Council, in a support case: members who upgraded partway through the year are billed the whole annual figure again with nothing knocked off, and staff correct each invoice by hand.
- Both attached to THEME-0002, and the editor stated its reason: in all of these, what the member already paid or is owed never reaches the amount billed.
- The assertion that checks it: the two T1 claims, worded completely differently, are attached to exactly one theme between them. It passes.

Asset: `t1_side_by_side`, the two quoted claims rendered side by side above the theme title
and the editor's merge sentence. Caption: `../bi-theme-digest-store/digests/2026-W37.md,
theme 1` and `evals/golden_set.yaml, assertion S2`.

Speaker notes: This is the judgment half of the system doing the thing I pay a frontier model
for. A string match finds nothing here, and an embedding similarity finds it unreliably and
cannot tell you why it did. What I want from the editor is not just the merge but the stated
reason, because the reason is what a product manager reads to decide whether to trust the
merge. The reason also makes a wrong merge reviewable rather than invisible.

numbers:

- S2 passes, THEME-0002 from both T1 sources: `EvalResult.per_assertion.S2`
- claims 03a7ca4ae6d8 and 306b8bbab997: `EvalResult.per_assertion.T1a` and `.T1b`

---

## 8. The same feature under two names

Sentences on the slide:

- Trap T2: one customer says event check-in and another says attendee kiosk, and they mean the same capability.
- Cascadia Nurses Association needs event check-in to keep working when the venue wifi drops and to sync everything back afterwards. Atlantic Shipwrights Guild says that if the hall wifi cuts out the attendee kiosk has to carry on signing people in and catch up later.
- Both landed on THEME-0006, and the theme carries an aliases field reading event check-in and attendee kiosk, so the reconciliation is visible rather than implied.
- This is the post-acquisition vocabulary problem, named once: a company that grew by acquisition carries several names for the same capability, and the customers use whichever name their own product taught them.
- The aliases field is the cheap, auditable answer. Next week's claim matches on either name, and a reviewer can see which names were merged and disagree.

Asset: `t2_aliases_panel`, the theme file front matter showing the aliases list, above the two
source quotes. Caption: `../bi-theme-digest-store/themes/THEME-0006.md`.

Speaker notes: I name this once and do not labour it. Momentive Software is a group of
products that arrived from different places, so a theme store that keys on exact feature
wording would fragment a single problem across three names and under-count all three. The
aliases field is how the merge survives into next week: it is a field in the index the editor
reads first, so the reconciliation is context rather than a decision the model has to make
again from scratch every Monday.

numbers:

- S3 passes, aliases carry event check-in and attendee kiosk: `EvalResult.per_assertion.S3`
- claims dcb169d12187 and ae96fcdf3b0a on THEME-0006: `EvalResult.per_assertion.T2a` and `.T2b`

---

## 9. What the agent refused to surface

Sentences on the slide:

- Three things the corpus plants that must not come out the other end, and one that must come out ranked honestly.
- A private Salesforce case comment saying the account is a churn risk. It was never in the result set, because IsPublished equals true is in the SOQL itself rather than in a filter afterwards. Ten private comments were withheld across the sample run and the count is in the audit log.
- Five PII values redacted before any model call: one email, one phone, one address and two personal names. The scrubber runs before the document is stored and before any model sees it, and the audit log records counts by kind and never the value.
- A Momentive Software employee saying a lot of our customers ask for this. That is not a client claim. Speaker side is derived by code from the connector's participant record, so a staff quote is rejected at the verifier where it is a join, not in a prompt where it would be a hope.
- Trap T3 is the opposite case: a prospect's request is surfaced, not suppressed, and ranked below every customer backed theme. THEME-0009 scores 6.
- Four greps, four zero-hit results, all four in the eval.

Asset: `refusal_grep_panel`, captured terminal output of the must-not-appear greps and the
PII greps with their exit codes. Caption: `evals/results.md, must not appear section`.

Speaker notes: The PII redaction count is five and it used to say ten. The scrubber was
counting the turn text and the per sentence copies of it, so the redaction was correct and
the count was doubled. An independent citation audit caught it, I fixed the scrubber and
regenerated the store, and I am telling you about it on the slide rather than quietly
shipping the corrected number. The employee remark trap is the one I am proudest of, because
it is caught by a deterministic join on the participant record rather than by asking the model
nicely.

numbers:

- 10 private comments withheld: `IntegrationManifest.corpus.comments_withheld`
- 5 PII redactions, 1 email, 1 phone, 1 address, 2 name: `B16.consolidation.what_actually_differs.scrub_counts`, and the W37 digest run line
- T4a and T4c pass: `EvalResult.per_assertion.T4a` and `.T4c`
- four PII assertions pass, 0 hits: `EvalResult.pii_grep_hits_whole_repo`
- S4 passes, THEME-0009 scores 10 on 3 prospect claims in the eval: `EvalResult.per_assertion.S4`
- THEME-0009 score 6 in the W37 ranking: `MetricsResult` drift block, reference ranked list, last row

---

## 10. Prioritization

Sentences on the slide:

- The score is code. The narrative is the model. The numbers are printed on the page so a reader can recompute them.
- score equals 30 times min(customers, 4) over 4, plus 25 times min(ARR, 500000) over 500000, plus 20 times min(open cases, 4) over 4, plus 15 times max(0, 14 minus days since last evidence) over 14, plus 10 times min(claims, 3) over 3.
- Rounding is floor of the total plus a half, clamped to the range 0 to 100, because banker's rounding lets two correct implementations disagree on a half value.
- THEME-0002 worked: 15.00 plus 24.70 plus 20.00 plus 10.71 plus 10.00 equals 80.41, which rounds to 80.
- Beside it, the editor's sentence: two customers are sending members numbers they then have to apologise for.
- One of those two is checkable with a calculator. The other is the reason anybody reads the digest at all.

Asset: `score_function_panel`, the score function source beside the rendered why this score
line from the digest. Caption: `src/digest/score.py` and
`../bi-theme-digest-store/digests/2026-W37.md, theme 1`.

Speaker notes: The rule I followed everywhere is that deterministic code does anything a
join, a regex or arithmetic can do. A model asserting a priority score is a number nobody can
check and everybody has to trust. A model writing the sentence that explains why a score
matters is a model doing the thing it is good at. The weights are mine and they are arguable,
which is the point of printing them: the argument is about the weights, not about whether the
number is real.

numbers:

- THEME-0002 score 80 and its five terms: the why this score line in `../bi-theme-digest-store/digests/2026-W37.md`, theme 1, and `MetricsResult` drift block, reference ranked list, first row
- verify horizon 14 days: `docs/DECISIONS.md` decision 34, stated once in the contracts

---

## 11. The digest

Sentences on the slide:

- This is what a product manager actually reads, and it is a file and a page rather than a service.
- The run line at the top reports the week as work done: sources read split into calls and cases, private comments withheld, PII redactions, claims verified and rejected, themes appended and opened, and cost.
- Week 2026-W37: 25 sources read, 14 calls and 11 cases, 4 private comments withheld, 5 PII redactions, 27 claims verified, 0 rejected, 0 themes appended, 10 opened, 2.27 US dollars for the week.
- Each theme carries a paragraph in plain sentences, then the evidence, each quote tagged with the account, the call or case, the timestamp, the speaker and the claim id.
- A thin week is visible on the page a product manager already reads, which is the failure mode I care most about: not an error, a digest that looks normal and is quietly missing a day.

Asset: `digest_page_panel`, a real rendered page of the W37 digest with one theme's evidence
block expanded and one claim id circled. Caption:
`../bi-theme-digest-store/digests/2026-W37.md`.

Speaker notes: I spent real effort on the run line and I would defend it. The digest is the
surface the team already opens, so the operational health of the pipeline belongs on it
rather than in a dashboard nobody has a reason to visit. If sources read drops from twenty
five to four, the person reading the digest sees it in the first line without knowing
anything about the pipeline. That is cheaper and more reliable than an alert routed to
somebody on holiday.

numbers:

- the whole run line: `../bi-theme-digest-store/digests/2026-W37.md`, run line, which is the rendered form of `MetricsResult.three_week_totals` week `2026-W37` plus `B16.consolidation.what_actually_differs.scrub_counts` for the redaction count
- 2.27 US dollars for the week: `MetricsResult.three_week_totals.2026-W37`
- 27 claims verified, 0 rejected: `MetricsResult.three_week_totals` week `2026-W37`

---

## 12. Governance

Sentences on the slide:

- Seven controls, each with the command that demonstrates it, because a governance claim that cannot be run is a paragraph rather than a control.
- 1. PII removed before the model. Grep the scrub events, grep for a planted value: 53 scrub events, no planted value anywhere in the store.
- 2. Every action audited, reads included. One validated event per line, and reads are logged so what did it touch is a query rather than a guess.
- 3. Private case comments never in the result set. 10 withhold events across the 15 ingest runs.
- 4. Structured output rejected, never patched. 55 accepted, the rejected directory empty, all five rejection reasons at zero.
- 5. Every claim resolves to its source. The eval prints 55 citations resolved.
- 6. Least privilege at the tool boundary. Four read tools on the editor. A grep for a write tool matches nothing.
- 7. A human gate before any system of record. The dry run prints the issue and files nothing. The same command without the confirmation exits 4, refused.
- Failure behaviour is rejection over repair, with exit codes fixed so a red job is readable without opening the log.

Asset: `governance_commands_panel`, the seven control commands with their real captured
output, rendered as a terminal panel. Caption: `docs/GOVERNANCE.md, the seven controls`.

Speaker notes: This is written for an IT and security reader who will not read the code. The
sentence under it is that a control you can run beats a control you can describe, and every
row here is a command somebody can paste. The NIST AI RMF mapping is in the document and I
have deliberately not put it on a slide, because a framework mapping on a slide is decoration
and in a document it is a reference. If asked about the kill switch: disable the two
workflows and the agent stops at its next tick, and nothing here holds a queue that keeps
draining after the switch is thrown.

numbers:

- 53 scrub events: `docs/GOVERNANCE.md` control 1, and one scrub per source document, `MetricsResult.three_week_totals` sources total 53
- 10 withhold events: `IntegrationManifest.corpus.comments_withheld`
- 55 accepted, 0 rejected, five reasons at zero: `MetricsResult.three_week_totals.claims_verified`, `.claims_rejected`, `IntegrationManifest.rejected_by_reason`
- 55 citations resolved: `EvalResult.per_assertion.S1`
- four read tools: `docs/GOVERNANCE.md` control 6
- exit 4 on the refused approve: `docs/GOVERNANCE.md` control 7

---

## 13. Evals

Sentences on the slide:

- A golden set of 18 assertions, run with one command, and the exit code is the result.
- Five must-appear: the two differently worded renewal claims, the two differently worded event check-in claims, and the prospect's SCORM request, each of which has to appear in the store, cited, attached to a theme and quoted in the digest.
- Two must-not-appear: the private churn risk comment and the Momentive Software employee remark. Both checked by grep over the whole store, with the exact commands and their exit codes published.
- Four PII assertions, one per planted value, checked with no location excluded.
- Seven structural assertions: every citation resolves, the two T1 claims land on one theme, the T2 theme carries both product names in its aliases, the prospect theme ranks below equal-sized customer themes while still appearing, no planted PII anywhere, a rebuild produces the same theme ids, and the stale flag fires on the one theme that received nothing for two weeks.
- Result: 18 of 18 passed, exit code 0, in replay, with zero network calls and zero live model spend.

Asset: `eval_run_panel`, captured output of the eval command with the per assertion lines and
the exit code. Caption: `$ python -m digest eval --mode replay`.

Speaker notes: The honest thing to say about this golden set is that I wrote all of it, which
is its weakness, and I say so in the future builds document. What it is good for is
regression: it caught a real reader recall miss twice, and the fix was a prompt version bump
rather than a patch to the output. Assertion T2b failed in runs one and two and passes in run
three, which is the eval loop doing the job it exists to do. Every assertion that ever failed
was a week 37 assertion and both failures were the same underlying problem.

numbers:

- 18 assertions, 18 passed, 0 failed, exit 0: `EvalResult.assertions_total`, `.assertions_passed`, `.assertions_failed`, `.exit_code`
- 55 citations resolved: `EvalResult.per_assertion.S1`
- 0 PII hits across the whole repository: `EvalResult.pii_grep_hits_whole_repo`
- T4a 0 hits, T4c 0 hits in outputs: `EvalResult.must_not_appear_grep_hits`
- T2b history, fail, fail, pass: `MetricsResult.eval_per_week.assertions`, entry T2b

---

## 14. Drift, measured

Sentences on the slide:

- The same week was built twice, live, against the same 27 claims, and the second opinion was recorded into a scratch copy so it could never overwrite the first.
- Claim co-assignment Jaccard: 1.000. Every unordered pair of claims that landed on the same theme landed on the same theme both times. The two builds partitioned all 27 claims identically, ten piles against ten piles.
- The strict overlap including the allocated theme id reads 0.227273, and the gap between those two numbers is the whole story.
- The top three looked like it changed and it did not. Both builds ranked the same three themes in the same order with the same scores, including the 75 against 75 tie, and gave them different four digit ids, because ids are handed out in the editor's placeholder order and week 37 is a cold start into an empty index.
- So the flag now compares the claim set each of the top three carries and reads true, and the old id comparison is reported beside it and still reads false.
- Publishing both is the honest presentation. A metric that flips on a relabelling was worth finding. A metric that keeps flipping after you know why is noise.

Asset: `drift_table_panel`, the two ranked lists side by side with scores and a same claims
column. Caption: `docs/metrics/cost_table.md, section 7`.

Speaker notes: This is the slide where I would rather be believed than impressive. The first
live run of the whole pipeline agreed with itself at 0.79 and I published that too. The fix
was not to tune until the number looked better, it was to find three separate causes, fix
each at the thing that owned it and re-run end to end. If somebody asks whether 1.000 is
suspicious: it is measured over a 27 claim week with a cold start store, and I would expect it
to fall on a larger corpus, which is why drift is a scheduled job in the future builds
document rather than a one-off measurement.

numbers:

- 27 claims: `MetricsResult.three_week_totals` week `2026-W37`, claims verified
- claim co-assignment Jaccard 1.000: `MetricsResult.drift_two_live_w37_builds.claim_co_assignment_jaccard`
- labelled Jaccard 0.227273: `MetricsResult.drift_two_live_w37_builds.labelled_claim_to_theme_jaccard`
- 10 themes against 10: `MetricsResult.drift_two_live_w37_builds.themes`
- second opinion cost 0.495435 US dollars: `MetricsResult.drift_two_live_w37_builds.second_opinion_usd`
- top3 stable true by claim set, false by id: `B16.consolidation.stability_result.top3_stable` and `.top3_stable_by_id`
- the three scores 80, 75, 75: `MetricsResult.drift_two_live_w37_builds.first_build_top3_with_scores`
- run 1 Jaccard 0.792: `IntegrationManifest` three run headline table, row W37 live rerun claim co-assignment jaccard

---

## 15. Cost

Sentences on the slide:

- Measured, not estimated. Every figure comes out of the committed audit logs, and a script in the repository recomputes all of it from the store and nothing else.
- Week 2026-W37 by stage: extract, 25 calls at the extraction tier, 1.052313 US dollars. Edit, 2 calls at the synthesis tier, 1.218660 US dollars. Total 2.270972.
- The same week with every stage on the frontier model would be 6.480224, a 2.8535 times bill, for work the golden set says the cheap tier already does correctly. Routing saves 4.209252 US dollars a digest week.
- At ten times the volume, extraction is 92.75 percent of the tokens and 46.3 percent of the cost, the week is 22.709720 and frontier everywhere is 64.802240, so the tier map saves 42.092520 a week and the saving grows with the column that grows.
- Rerunning the same week with every tier on the small model costs 0.283140, which is 23.23 percent of the reference build, groups the claims identically at Jaccard 1.000, and passes the same assertions.
- Two costs are reported everywhere and labelled: 4.687941 by the published rate table against 5.755600 by the provider's own accounting, a ratio of 1.2277, because the provider bills a one hour cache write higher than the table does.

Asset: `cost_tables_panel`, the by stage table and the ten times projection rendered as one
figure. Caption: `docs/metrics/cost_table.md, sections 1 to 3`.

Speaker notes: The extract multiple is exactly 5.0000 and that is not a coincidence: every
frontier rate here is exactly five times the cheap rate, so moving any stage between those two
models multiplies its bill by five whatever the token mix. The number I would draw attention
to is the cache column. Non-cached input for the whole week is 538 tokens and cache read is
2.45 million, because passing a contract schema writes a large preamble once per run and reads
it back at a tenth of the input rate afterwards. That is most of the reason a week costs two
dollars and not twenty. The swap result is the uncomfortable one and I publish it: the cheap
model grouped this week identically for 23 percent of the money, and I still route synthesis to
the frontier model, on a 27 claim cold start week that is not enough evidence to downgrade.

numbers:

- extract 25 calls, 1.052313: `MetricsResult.sample_run.by_stage.extract.calls` and `.router_table_usd`
- edit 2 calls, 1.218660: `MetricsResult.sample_run.by_stage.edit.calls` and `.router_table_usd`
- week total 2.270972: `MetricsResult.sample_run.router_table_usd`
- frontier everywhere 6.480224, delta 4.209252, multiple 2.8535: `MetricsResult.repriced_on_claude_opus_5`
- 10x: 22.70972, 64.80224, saving 42.09252, token share 92.75, cost share 46.3: `MetricsResult.projection_at_ten_times`
- swap 0.28314, 23.23 percent, Jaccard 1.0: `MetricsResult.swap_models_2026_W37`
- 4.687941 against 5.7556, ratio 1.2277: `MetricsResult.cost_two_ways`
- 538 tokens in, 2452742 cache read: `MetricsResult.sample_run.by_stage`, summed, and `docs/metrics/cost_table.md` section 1 total row

---

## 16. Agnostic by construction

Sentences on the slide:

- Application code asks for a tier and never for a model. A model id under the source tree is a build failure, asserted by a test.
- Three tiers: extraction, synthesis, narrative. One runtime file names a model, `config/models.yaml`, and swapping the map is that one file.
- The swap is demonstrable rather than described: one command reruns a week against a different tier map and prints cost, eval pass rate and theme assignment overlap against the reference.
- Providers sit behind one adapter interface with capability negotiation. The router picks the strongest path a provider declares: native structured output first, then a strict tool call, then the schema in the prompt with validation and one retry in code. Same contract, three implementations, one call site, and the chosen path is in the audit log.
- Sources sit behind a connector protocol with two methods. A new source is a new file and a config entry with no pipeline change.
- The router already stepped down a path once in this build, when one contract shape was refused by one transport, and it logged which path ran rather than reshaping the contract.

Asset: `models_yaml_panel`, the tier map beside the provider capability declaration. Caption:
`config/models.yaml` and `src/digest/providers/base.py`.

Speaker notes: The question behind this slide is the one about cheaper models arriving through
gateways and routers, and a tier abstraction with a one file swap is my answer to it. The part
I would emphasise is capability negotiation rather than the tier map, because the tier map is
easy and the negotiation is where a provider swap actually breaks. Thinking configuration is
derived from the model family in code rather than sitting in the config file, because the
interfaces differ between families in ways that return a 400 rather than a warning, and a
budget in a config file would invite an error the config file cannot explain.

numbers:

- three tiers: `docs/DECISIONS.md` decision 13
- swap cost 0.28314 at 23.23 percent, eval 16 of 16 both sides: `MetricsResult.swap_models_2026_W37`

---

## 17. The build was itself an agent system

Sentences on the slide:

- The thing being demonstrated is not only the product. This deliverable was built by a parallel fanout of single purpose agents under one orchestrator, which is the job being hired for.
- Six waves, thirty worker tasks, one envelope returned per worker. The orchestrator holds the plan and reads envelopes. It does not read source files.
- Four model tiers ran the build and the roster is committed. The orchestrator on one model, the writer and reviewer tier on the frontier model, the cheap tier on a mid model.
- The plan named a different cheap tier and the harness offered a different one, so the file records what actually ran rather than what was planned.
- The product's own numbers are the proof the shape worked: 55 claims, 0 rejected, 18 of 18 assertions, byte identical replay.

Asset: `wave_plan_panel`, the wave plan rendered as a simple ASCII flow with worker counts per
wave. Caption: `build/envelopes, one per worker`.

Speaker notes: I include this because the seat is an AI operations job and how the thing was
built is at least as interesting as what it does. The orchestrator never reading source files
is the load bearing part. An orchestrator that reads what its workers wrote becomes the
context bottleneck the fanout existed to avoid, and then it starts making decisions the worker
already made better. It reads a structured envelope with an assumptions array, and when two
envelopes disagree it is a visible conflict rather than a silent one.

numbers:

- six waves, thirty worker tasks: the build envelope set, `build/envelopes/B1.json` through `B30.json`, one per worker. This is a build side count rather than a product manifest field, and it is labelled as such.
- four build model tiers: `docs/DECISIONS.md` decision 45, and `config/build_models.yaml`
- 55 claims, 0 rejected: `MetricsResult.three_week_totals`
- 18 of 18: `EvalResult.assertions_passed`

---

## 18. What stops a parallel build from rotting

Sentences on the slide:

- Four rules, written down before any fanout, because context rot is the failure mode of a large agent build and a bigger context window is not the fix.
- A contract pack first. Every schema was written and frozen before a single worker started, so no worker ever had to guess what another worker would return.
- Exclusive file ownership. Every worker owns a set of paths and writes nowhere else, so two agents never race on one file and a merge conflict is a planning bug rather than a runtime one.
- Self-contained briefs. A worker receives only the contract slice it needs and never talks to another worker, so a brief is testable on its own and a worker that fails can be re-run without replaying the build.
- Structured envelopes with an assumptions array. Anything a worker inferred rather than being told goes in a named array rather than buried in code, which is how the decision log on the next repository page came to exist at all.
- The same rule runs inside the product: no agent returns prose to another agent, every call returns a named versioned schema, validated in code, retried once with the error appended, then rejected and logged.

Asset: `envelope_panel`, a real envelope rendered with its assumptions array highlighted.
Caption: `build/envelopes/B18.json`.

Speaker notes: The assumptions array is the rule I would carry to any team. Every agent infers
something, and the difference between a build you can audit and one you cannot is whether
those inferences are collected in a named place or scattered through code as silent choices.
Reading thirty assumptions arrays is how I found the places where two workers had inferred
opposite things from the same specification sentence, and that is a specification bug that
would otherwise have shipped.

numbers: none on this slide. The four rules are structural, from `docs/DECISIONS.md` decision
44 and `build/COMMON_RULES.md`.

---

## 19. The QA wave that built nothing, and acceptance

Sentences on the slide:

- One whole wave of agents wrote no product code. Their only job was to try to break what the previous waves had shipped.
- A citation auditor that resolved claims by hand, opening the source files itself and checking the quoted text, without using the pipeline's own verifier. Reason: a verifier that is wrong in the same direction as the extractor is invisible to itself.
- It sampled 30 claims including all 8 trap claims, resolved 30 of 30, then swept all 55 and all 125 digest evidence lines, and found 0 unresolved.
- It also raised two soft findings. One was real: the digest reported ten PII redactions where five values were planted, because the scrubber counted the turn text and the per sentence copies of it. The redaction was right, the count was doubled, and the fix and the store regeneration are in the repository.
- A compliance sweep over both repositories: 0 real findings on dash characters, non-ASCII, secrets, stray real email addresses, URL-shaped text, lowercase company name and voice drift, and 0 model ids under the source, MCP and tools trees.
- A portability agent cloned the repository as a stranger and found a real defect: the weekly build was not idempotent, so a clone of the published store rebuilt weeks it already had. Fixed at the root, with a test.

Asset: `citation_audit_panel`, the audit's own summary table. Caption:
`build/envelopes/B25.json, measured.CitationAudit`.

Speaker notes: The sentence I want to land is the one about a verifier wrong in the same
direction as the extractor. Checking a citation with the same code that produced it proves the
code is self consistent and nothing else. The audit found a real bug that the pipeline's own
assertions could not see, which is exactly the return I wanted for the wave. The portability
defect is the one that would have embarrassed me most, because it only appears in a stranger's
fresh clone, which is the only environment that matters for a repository I am asking somebody
to open.

numbers:

- 30 sampled, 30 resolved, 0 unresolved: `CitationAudit.sampled`, `.resolved`, `.unresolved`
- 8 trap claims all covered: `CitationAudit.trap_ids_all_covered`
- 55 of 55 full sweep, 125 evidence lines, 0 bad: `CitationAudit.full_sweep_claims_total`, `.full_sweep_claims_resolved`, `.digest_evidence_lines_checked`, `.digest_evidence_lines_bad`
- 0 must-not-appear hits, 0 PII hits: `CitationAudit.must_not_appear_hits`, `.pii_hits`
- compliance real findings by category: `ComplianceReport.category_counts`, and 0 model ids under src, mcp and tools at `ComplianceReport.category_counts.6_model_ids_in_code_dirs.src_mcp_tools_hits`
- acceptance re-audit after the portability fix: `AcceptanceReport.rerun_after_portability_fix`. If that key is absent at build time this line reads that the acceptance re-audit was still running when the deck was built, and no acceptance figure is printed.

---

## 20. In production

Sentences on the slide:

- Nightly ingestion off a watermark. The store carries a last ingest run and a last ingest day, and each night pulls only what is newer, so nothing is fetched twice and a skipped night shows as a thin run rather than as silence.
- The MCP connectors are swapped for the real APIs. The mock already serves the real response shapes including cursor pagination, so the change is a base URL and a credential with no translation layer.
- Scoped read-only credentials, one identity per agent, not one shared service account, because an audit log that says the integration user did it answers nothing. Secrets in a vault, read at start up, never on disk.
- The approval gate stays in front of any system of record. The agent proposes, a person files, and the agent only earns more room against a measured acceptance rate rather than against time served.
- On Bedrock: I would run this on the Claude platform or the API directly, because the constraint here is speed of adoption and the platform's own identity and audit already satisfy the requirement. I would reach for Bedrock when the constraint is data residency in a named region, IAM native identity, private networking, or consolidated AWS billing. The router exists so that is a one file change.

Asset: `watermark_panel`, the sources index watermark lines beside the ingest entry point.
Caption: `../bi-theme-digest-store/sources/_INDEX.md`.

Speaker notes: The Bedrock answer is two sentences and I keep it to two, because a long answer
reads like a preference and a short one reads like a decision. The thing that actually differs
between the platforms is model id translation, and that detail is the difference between a
swap taking an hour and taking a day. On the schedule: two workflows are committed and both
run green with no secret configured, because they run in replay against the committed corpus.
That is deliberate and it is stated as a comment in the workflow file.

numbers:

- 15 nightly ingests, 53 source documents, 55 claims: `IntegrationManifest.corpus.ingest_days_run`, `.source_documents`, `.claims_verified`
- per day claim counts from 11 down to 0: `IntegrationManifest.claims_per_ingest_run`

---

## 21. Future builds

Sentences on the slide:

- Nine items are written down, ordered, each with what it needs to be safe. None of it is built, and saying so is the point. Here are the first four.
- 1. A golden set that grows itself, from human corrections, rejected claims and production incidents. Needs a correction mechanism on the digest surface first, because without somewhere to say this one is wrong there are no corrections to learn from.
- 2. An adaptive eval agent, gated. It reads the run logs, finds the intents whose pass rate is sliding, and opens a pull request. It does not merge. Needs per intent scoring, because an agent that can only see an aggregate pass rate will guess.
- 3. Trust tiers on the filing gate: propose only, then draft into an approval queue, then file directly within a named scope and budget. Needs proposal acceptance tracked per theme type, so widening is a number rather than a feeling. Widen on evidence, never on time served.
- 4. Drift detection as a scheduled job rather than a reported metric, alerting on thin runs and not only on failed ones. Needs a recorded expectation of volume per source per day, because without it a quiet week and a broken connector look identical.

Asset: none. This slide is prose.

Speaker notes: The adaptive eval agent is the one I would most like to build and the one I
deliberately did not build, because it is the item where the gate matters most and a gate
bolted on afterwards is not a gate. The pull request is the right approval surface precisely
because it is a control the team already has and already trusts, rather than a new queue
somebody has to be persuaded to own. Item four is the failure I keep coming back to: the worst
outcome for a digest agent is not an error, it is a week that reads perfectly normal and is
missing a day of calls.

numbers: none on this slide. The four items are from `docs/FUTURE_BUILDS.md`, items 1 to 4.

---

## 22. What I cut, and why

Sentences on the slide:

- Real Gong and Salesforce API integration. The brief said mock, and the MCP boundary is the seam that makes the swap a credential change.
- A web UI or a hosted service. The digest is a file and a page, because that is what a product team actually reads.
- Authentication, multi-tenancy and role based access on the store. Git permissions are the prototype's access control and I would not ship that.
- The adaptive eval agent that updates other agents' context. It is the right next stage and it belongs behind the same gate, so it is designed in the document and not built.
- Vector retrieval. At this corpus size the theme index is smaller and more auditable than an embedding store. When it stops fitting comfortably in layer one, retrieval goes behind a tool with citations required.
- Slack or Teams delivery. One connector, no new thinking, not worth the hours.
- Everything above is a decision with a reason attached, which is the same standard I held the agent to.

Asset: none. This slide is prose, taken straight from the repository README.

Speaker notes: I end on what I cut rather than on what I would build next, because scope
discipline is the harder thing to demonstrate and the more useful thing to know about somebody
you are about to hire. Each of these was a real temptation and each one has a reason written
next to it in the README, which is where I would want a reviewer to check whether the reason
holds up. If there is time for one question at the end, I would rather it be about the cut list
than about the roadmap.

numbers: none on this slide. All six items are from `README.md`, what I cut and why.

---

## Assets index

Every asset named above resolves to an entry in `deck/assets/manifest.json`, produced by the
asset worker. Each one is placed at legible size with its caption underneath in the muted grey,
naming the file or the command it came from. If an asset is missing from the manifest at build
time, its slide carries the sentences and a one line note saying which panel is missing, rather
than a placeholder box.

## Rules this outline was written under

- Every number on a slide appears in that slide's `numbers:` list with a manifest field path.
- No em dash and no en dash anywhere, speaker notes included.
- Momentive Software in full on first use, never lowercase.
- Real sentences on every slide, because the deck has to be comprehensible with nobody
  presenting it.
- No logos, mine or theirs.
- If a measurement is missing, the slide says the measurement is missing rather than carrying
  a plausible figure. In a deck about traceability that is the one unrecoverable mistake
  available.
