# Cost, tokens and drift, measured

Every number on this page comes out of the audit logs of the live sample run. Nothing here is an estimate, a list price multiplied by a guess, or a number I remembered. `docs/metrics/recompute.py` reads the context store and recomputes all of it, and `docs/metrics/metrics.json` is that script's output verbatim. If a number here disagrees with the script, the script is right.

The sample is week 2026-W37: five ingest runs and one build run, six run directories, 347 committed audit log lines, 27 model calls. Run ids are in every table so any figure can be traced back to a file.

Two costs are reported throughout, and they are not the same number:

- **Router table cost.** Every call priced from the rate table in `config/models.yaml`, which is the published rate: `claude-haiku-4-5` at $1.00 per million input and $5.00 per million output, `claude-opus-5` at $5.00 and $25.00, cache read at a tenth of input and cache write at 1.25 times it. This is what `cost_usd` on each `call_model` line holds, and `recompute.py` re-prices all 63 calls in the store from the table and confirms it matches the log to ten decimal places.
- **CLI reported cost.** What the `claude` CLI billed itself, from `total_cost_usd` on the result. It is higher, because the CLI charges a one hour cache write at 2.0x input where the table says 1.25x. The committed store was regenerated in replay and a replayed call has no bill, so the CLI figures are carried into the script as declared constants measured during the live run. They are labelled as such everywhere they appear.

## 1. The sample digest run, by stage and by tier

Week 2026-W37. Ingest runs `2026-09-07T06:00Z` through `2026-09-11T06:00Z`, build run `2026-09-14T07:00Z`.

| stage | tier | model | calls | tokens in | tokens out | cache read | cache write | router table USD |
|---|---|---|---|---|---|---|---|---|
| extract | extraction | claude-haiku-4-5 | 25 | 532 | 126,559 | 2,389,958 | 143,992 | 1.052313 |
| edit | synthesis | claude-opus-5 | 2 | 6 | 14,926 | 62,784 | 130,254 | 1.218660 |
| **total** | | | **27** | **538** | **141,485** | **2,452,742** | **274,246** | **2.270972** |

Stage and tier are one to one in this run because only two agents make calls in a digest week: the two readers at the extraction tier in the extract stage, and the editor's two calls at the synthesis tier in the edit stage. The narrative tier only appears when the analyst is asked a question, which is a separate run type and is reported in section 5.

Per run, with the log line count each figure is traceable to:

| run id | type | log lines | model calls | sources read | claims verified | router table USD |
|---|---|---|---|---|---|---|
| 2026-09-07T06:00Z | ingest | 5 | 0 | 0 | 0 | 0.000000 |
| 2026-09-08T06:00Z | ingest | 71 | 9 | 9 | 11 | 0.367719 |
| 2026-09-09T06:00Z | ingest | 56 | 7 | 7 | 7 | 0.317343 |
| 2026-09-10T06:00Z | ingest | 45 | 5 | 5 | 5 | 0.171639 |
| 2026-09-11T06:00Z | ingest | 35 | 4 | 4 | 4 | 0.195611 |
| 2026-09-14T07:00Z | build | 135 | 2 | 0 | 0 | 1.218660 |

`runs/2026-09-14T07:00Z/week_summary.json` independently totals the week at 2.270972, computed by the pipeline from the same logs. The two agree.

One number deserves an explanation before anyone reads the cache column as a mistake. Non cached input is 538 tokens for the whole week, and cache read is 2.45 million. Passing a contract schema to the CLI adds a preamble of 27K to 42K tokens; the CLI writes it to a one hour cache on the first call of a run and reads it back at ten percent of input for every call after. So almost all input in this pipeline is cached input, by design, and the cheap rate on that column is most of why the week costs two dollars and not twenty.

Cost the other way, for the same week: I do not have a per week CLI figure broken out, only the phase totals from the live run. Across the whole store the CLI billed 5.7556, a figure measured before the third analyst question and carried forward as a declared constant, against the table's 5.067601, a ratio of 1.1358, and the section 5 table gives the split.

## 2. The same run with every stage on the frontier model

The routing decision is worth exactly what it saves, so here is the subtraction. Re-pricing means taking the identical token counts, which is the honest comparison for extraction because the readers already validated on the first attempt at the cheap model, and pricing them at the frontier rate.

Extraction, repriced at `claude-opus-5`:

```
(532 in x $5.00 + 126,559 out x $25.00 + 2,389,958 cache read x $0.50 + 143,992 cache write x $6.25) / 1,000,000
= (2,660 + 3,163,975 + 1,194,979 + 899,950) / 1,000,000
= $5.261564
```

| stage | model as run | router table USD as run | on claude-opus-5 | multiple |
|---|---|---|---|---|
| extract | claude-haiku-4-5 | 1.052313 | 5.261564 | 5.0000 |
| edit | claude-opus-5 | 1.218660 | 1.218660 | 1.0000 |
| **total** | | **2.270972** | **6.480224** | **2.8535** |

The extract multiple is exactly 5.0000 and that is not a coincidence: every one of the four `claude-opus-5` rates is exactly five times the `claude-haiku-4-5` rate, so moving any stage between those two models multiplies its bill by five whatever the token mix. Putting the readers on the frontier model costs $4.209252 more per digest week, a 2.85x bill, for work the golden set says the cheap model already does correctly.

## 3. Ten times the volume

Twenty five sources a week is a pilot. The shape I care about is what happens at 250. I scale token counts linearly with source count: the readers see ten times as many documents at the same size, and the editor's two calls stay two calls but carry ten times the claims and write ten times the decisions. The cache preamble is per call, so it scales with calls, which is what the linear scale already does.

| stage | calls at 10x | tokens at 10x | share of tokens | router table USD at 10x | share of cost |
|---|---|---|---|---|---|
| extract | 250 | 26,610,410 | 92.75% | 10.523130 | 46.3% |
| edit | 20 | 2,079,700 | 7.25% | 12.186600 | 53.7% |
| **total** | **270** | **28,690,110** | | **22.709720** | |

That table is the whole routing argument in two columns. Extraction is 92.75 percent of the token count and under half the cost, because token count is exactly what you do not want on the frontier model. The same week with every stage on `claude-opus-5` is $64.802240, so the tier map saves $42.092520 a week at ten times the volume, and the saving grows with the extraction column, which is the column that grows.

## 4. Tokens per stage

The token table is section 1 and I am not going to repeat it. What it says, in one line each:

- **extract**: 25 calls, 2,661,041 tokens, of which 2,389,958 are cache reads. High call count, small unique input, large output, cheap model.
- **edit**: 2 calls, 207,970 tokens, of which 130,254 are cache writes. Two calls, one of them writing 14,817 tokens of decisions in a single response, frontier model.

The editor writes more tokens per call than every reader in the week put together writes in nine.

## 5. Three weeks

Fifteen ingest runs, three builds, 1,079 committed audit log lines, 63 model calls store-wide. The store also carries two run directories whose manifest was never committed, the analyst ask run and the approve dry run, so the raw line count over `runs/` reads higher than 1,079, now 1,136 lines, and grows every time somebody runs the dry run again. A third analyst question was recorded live after the sample run, as a paraphrase reproduced during QA, and its calls landed in the same unmanifested ask run directory, so it is included in the store total below without adding a new run directory or changing the manifested-run figures. `recompute.py` reports both counts and every cost figure on this page is taken from the eighteen runs that carry a manifest, except the ask line below.

| week | ingest runs | sources read | claims verified | rejected | themes appended | themes opened | proposal files | ingest USD | build USD | week USD |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-W37 | 5 | 25 | 27 | 0 | 0 | 10 | 6 | 1.052313 | 1.218660 | 2.270972 |
| 2026-W38 | 5 | 16 | 16 | 0 | 7 | 1 | 5 | 0.593559 | 0.438325 | 1.031884 |
| 2026-W39 | 5 | 12 | 12 | 0 | 8 | 0 | 4 | 0.494158 | 0.458586 | 0.952744 |
| **total** | **15** | **53** | **55** | **0** | **15** | **11** | **15** | **2.140030** | **2.115571** | **4.255600** |

These totals are summed from the raw log lines. The pipeline's own `week_summary.json` sums each run's already rounded manifest instead, so week 38 reads 1.031882 there against 1.031884 here, two millionths of a dollar apart. The other two weeks agree exactly. `recompute.py` prints the difference rather than hiding it.

The three analyst questions ran outside a digest week and cost 0.812001 over 4 calls at the narrative tier, which brings the whole store to 5.067601 by the table. Both costs, by phase:

| phase | router table USD | CLI reported USD | ratio |
|---|---|---|---|
| ingest | 2.140030 | 2.3666 | 1.1059 |
| builds | 2.115571 | 2.7244 | 1.2878 |
| ask | 0.812001 | 0.6646* | * |
| **store total** | **5.067601** | **5.7556*** | **1.1358** |

\* The CLI reported figure for the ask phase, and the store total CLI figure, were measured on the live run before the third analyst question and are carried forward as declared constants rather than invented for the new call; no per-phase ratio is given for the ask row because it would mix a pre-third-question CLI number against a post-third-question router number. `recompute.py` does print the store total ratio, 1.1358, so that cell is recomputed.

Including the stability second opinion and the model swap, which run into scratch copies rather than into the store, the live run spent 5.4664 by the table and 6.69 by the CLI, a ratio of 1.2238, against a ceiling of about twenty dollars.

The cost curve across the three weeks is the point. Week 37 is a cold start into an empty store, so every claim opens a theme and the editor writes ten of them. By week 39 the store does the work: eight themes get appended to, none are opened, and the week costs 42 percent of week 37.

## 6. The model swap

`digest swap --models config/models.cheap.yaml --week 2026-W37` reruns the same week with every tier on the small model and compares. Both sides are committed, as `runs/2026-09-14T07:00Z/responses` and `runs/2026-09-14T07:00Z/responses-swap`, so the comparison replays for free.

| | reference tier map | cheap tier map |
|---|---|---|
| synthesis model | claude-opus-5 | claude-haiku-4-5 |
| build cost, router table USD | 1.218660 | 0.283140 |
| share of reference | 100% | 23.23% |
| themes | 10 | 10 |
| claim co-assignment Jaccard | | 1.000000 |
| claim to theme Jaccard, with ids | | 0.173913 |
| eval | 16 of 16 | 16 of 16 |
| top three | THEME-0002, THEME-0001, THEME-0006 | THEME-0007, THEME-0001, THEME-0003 |
| top three stable, by claim set | | true |
| top three stable, by allocated id | | false |

The small model groups this week's claims into exactly the same ten piles for 23 percent of the money and passes the same assertions. I still route synthesis to the frontier model, and section 7 is why the id columns in that table are not the reason.

## 7. Drift

Two builds of week 2026-W37 were run live against the same 27 claims. The first is the digest in the store. The second is a second opinion recorded into `runs/2026-09-14T07:00Z/responses-stability`, run into a scratch copy so it can never overwrite the first.

| measure | value |
|---|---|
| themes, first build against second | 10 against 10 |
| claim co-assignment Jaccard | 1.000000 |
| claim to theme Jaccard, with the allocated ids | 0.227273 |
| top three stable, by claim set | true |
| top three stable, by allocated id | false |
| second opinion cost, router table USD | 0.495435 |

Claim co-assignment is the label independent measure: every unordered pair of claims that landed on the same theme. At 1.000000 the two builds partitioned all 27 claims identically, ten piles against ten piles, not one claim moved. The second number, 0.227273, is the strict pair overlap including the allocated theme id, and the gap between the two is the entire story of this section.

### Why the top three looked like it changed

`top_three` sorts by score descending then theme id ascending and returns three ids. Theme ids are allocated by `store.allocate_theme_ids`, which sorts the editor's `NEW-n` placeholders by their numeric suffix. Week 37 is a cold start, so the index is empty and `NEW-n` becomes `THEME-000n`. The id a theme gets is therefore decided by the order the editor happened to list its new themes in, and the two builds listed them in different orders.

Here are both ranked lists side by side, scores included. Scores come from the `score` audit lines of the build run. A theme's score is a pure function of its evidence claims, the account enrichment and the as-of date, none of which differ between the two builds, so a pile of claims carries the same score on both sides.

| rank | first build | score | second opinion | score | same claims |
|---|---|---|---|---|---|
| 1 | THEME-0002 renewal amounts | 80 | THEME-0005 renewal billing | 80 | yes |
| 2 | THEME-0001 truncated exports | 75 | THEME-0001 truncated exports | 75 | yes |
| 3 | THEME-0006 offline event check-in | 75 | THEME-0003 offline event check-in | 75 | yes |
| 4 | THEME-0003 pledge reminders | 71 | THEME-0004 pledge reminders | 71 | yes |
| 5 | THEME-0005 accounting sync duplicates | 65 | THEME-0002 ledger sync duplicates | 65 | yes |
| 6 | THEME-0004 renewal notices to spam | 60 | THEME-0006 renewal notices to spam | 60 | yes |
| 7 | THEME-0008 joiners against tier upgrades | 53 | THEME-0008 joiners against tier upgrades | 53 | yes |
| 8 | THEME-0010 positive signal | 49 | THEME-0010 positive signal | 49 | yes |
| 9 | THEME-0007 job posting expiry | 44 | THEME-0007 job posting expiry | 44 | yes |
| 10 | THEME-0009 SCORM import | 6 | THEME-0009 SCORM import | 6 | yes |

The two rankings are identical position by position. Same ten piles of claims, same ten scores, same order, including the 75 against 75 tie at ranks two and three, which broke the same way on both sides because truncated exports was the editor's first listed theme in both. The only thing that differs is which four digit id sits in front of each row.

So the answer to the question the addendum asks is: **it is neither a real ranking difference nor a score tie broken differently. It is a renumbering, and the old `top3_stable` was measuring the ids rather than the themes.** Two specific checks rule out the alternatives:

- **Not different high importance counts from re-run readers.** `runs/2026-09-14T07:00Z/responses-stability` holds exactly two recordings and both are the editor's. Zero reader recordings, so the second opinion re-read nothing and scored the same claims. `recompute.py` counts those recordings rather than asserting it.
- **Not a tie broken differently.** The only tie is 75 against 75, and it resolves to truncated exports ahead of event check-in on both sides.

The same thing happens in the model swap in section 6, from the same cause: identical partition, identical ranking of themes, different ids. Three separate live builds of this week all produced the same ten piles in the same order.

What changed since this was first written: `pipeline._compare` now compares the top three by the set of claim ids each theme carries, the way `co_assignment` already does for the Jaccard number, so `top3_stable` reads true for both comparisons in this section. The old id comparison is not thrown away, it is reported beside it as `top3_stable_by_id` and it still reads false, because that is the fact that exposed the problem. Both numbers are in `runs/2026-09-14T07:00Z/stability.json`, which sits next to the manifest because `RunManifest.stability` is closed to four keys and carries only the label independent one. A metric that flips on a relabelling was worth knowing about; a metric that keeps flipping after you know why is just noise.

### Eval pass rate per week

Eighteen golden set assertions. Nine bind to week 37 evidence, one to week 39, eight are store wide, such as the PII sweep and the citation resolution check, and none bind to week 38 alone. Bindings for the claim and theme scoped assertions are checked against the claim lists in the build prompts rather than asserted.

| scope | assertions | run 1 | run 2 | run 3 |
|---|---|---|---|---|
| 2026-W37 | 9 | 8 of 9 | 7 of 9 | 9 of 9 |
| 2026-W38 | 0 | | | |
| 2026-W39 | 1 | 1 of 1 | 1 of 1 | 1 of 1 |
| store wide | 8 | 8 of 8 | 8 of 8 | 8 of 8 |
| **all** | **18** | **17 of 18** | **16 of 18** | **18 of 18** |

Every assertion that ever failed was a week 37 one, and both failures were the same underlying problem: a reader dropping a claim whose wording shares no vocabulary with the theme it belongs to. The 1.2.0 reader prompts fixed it and nothing else regressed.

## KPIs

The baseline is what the product team knows today without this running, which is whatever reached them through an account manager, and the measure is the delta after.

- **Cost per digest run.** Captured as `usage.total.cost_usd` in the run manifest, summed for the week in `week_summary.json`. Measured: $2.27, $1.03, $0.95 for the three weeks, ingest and build together.
- **Claims captured and rejected per run, with reasons.** Captured as `counts.claims_verified`, `counts.claims_rejected` and the `rejected_by_reason` block. Measured: 55 verified, 0 rejected across fifteen ingest runs, all five rejection reasons at zero.
- **Themes touched per digest, appended against opened.** Captured as `counts.themes_appended` and `counts.themes_opened`. Measured: 0 appended and 10 opened in week 37, 7 and 1 in week 38, 8 and 0 in week 39. A healthy store appends more than it opens once it has history, and this one crosses over in its second week.
- **Product team actions taken.** Captured as `counts.issues_filed`, with proposals written as the leading indicator. Measured: 15 proposal files across three weeks, 1 approval exercised as a dry run, 0 issues filed, because filing is gated behind an explicit `--yes` and nobody gave it one. This is the outcome metric, and the only one that says the digest changed anything.

## Recompute it

The whole page comes from `docs/metrics/recompute.py`, which reads the store and nothing else:

```bash
python docs/metrics/recompute.py --store ../bi-theme-digest-store
python docs/metrics/recompute.py --write     # rewrites docs/metrics/metrics.json
```

If you only want the totals, this is the part that matters and it stands on its own:

```python
import json, glob
from pathlib import Path

RATES = {  # dollars per million tokens
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-opus-5":    {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}
STORE = Path("../bi-theme-digest-store")

def price(model_id, event):
    r = RATES[model_id]
    return (event["tokens_in"] * r["input"] + event["tokens_out"] * r["output"]
            + event["cache_read"] * r["cache_read"]
            + event["cache_write"] * r["cache_write"]) / 1_000_000

by_stage, logged, repriced = {}, 0.0, 0.0
for path in sorted(glob.glob(str(STORE / "runs" / "*" / "run.log.jsonl"))):
    for line in open(path):
        event = json.loads(line)
        if event["action"] != "call_model":
            continue
        row = by_stage.setdefault(event["stage"], dict(calls=0, tokens_in=0, tokens_out=0,
                                                       cache_read=0, cache_write=0, cost_usd=0.0))
        row["calls"] += 1
        for field in ("tokens_in", "tokens_out", "cache_read", "cache_write"):
            row[field] += event[field]
        row["cost_usd"] += event["cost_usd"]
        logged += event["cost_usd"]
        repriced += price(event["model_id"], event)          # the rate table, independently

for stage, row in sorted(by_stage.items()):
    print(stage, row)
print("router table USD, from the log   %.6f" % logged)
print("router table USD, repriced here  %.6f" % repriced)
```

On the committed store that prints 5.067601 twice, over 63 model calls.
