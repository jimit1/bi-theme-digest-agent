# Cost and KPIs

I am Jim Mehta. This page pulls four cost numbers and four KPIs out of the real sample run, not out of estimates. Every figure below is copied verbatim from `docs/metrics/cost_table.md`, which itself is regenerated from the committed audit logs by `docs/metrics/recompute.py`. If a number here ever disagrees with that file, the file is right and this page needs a fix.

Two costs show up throughout, and they are not the same thing. The router table cost is every call priced from the published rate table in `config/models.yaml`: haiku-4-5 at $1.00 per million input and $5.00 per million output, opus-5 at $5.00 and $25.00. That is what the audit log carries. The CLI reported cost is what the `claude` CLI itself billed, which runs higher because the CLI charges a one hour cache write at 2.0x input where the table says 1.25x. I label every figure below with which one it is.

## 1. The sample run, by stage and model

Week 2026-W37, five ingest runs plus one build run, 27 model calls. Router table USD:

- extract, extraction tier, claude-haiku-4-5, 25 calls: $1.052313
- edit, synthesis tier, claude-opus-5, 2 calls: $1.218660
- total: $2.270972

Source: `docs/metrics/cost_table.md`, section 1.

## 2. The same run priced entirely on the frontier model

Repricing the identical token counts at claude-opus-5 rates puts extraction at $5.261564 instead of $1.052313, a 5.0000x multiple, because every opus-5 rate is exactly five times the haiku-4-5 rate. Edit stays at $1.218660 since it already runs on opus-5. Total on the frontier model: $6.480224 against the actual $2.270972, a 2.8535x bill, $4.209252 more per week. This is the routing decision quantified, not asserted. Source: `docs/metrics/cost_table.md`, section 2.

## 3. Projected cost at ten times the volume

Scaling sources tenfold: extract goes to 250 calls and 26,610,410 tokens, 92.75 percent of all tokens but only 46.3 percent of the cost, at $10.523130. Edit stays at 20 calls and $12.186600, 53.7 percent of the cost on 7.25 percent of the tokens. Total at 10x: $22.709720, against $64.802240 if everything ran on the frontier model, a $42.092520 weekly saving. Extraction is why it sits on the cheap model: it dominates token count and that is exactly what you do not want priced at the frontier rate. Source: `docs/metrics/cost_table.md`, section 3.

## 4. Tokens in and out per stage

- extract: 25 calls, 532 tokens in, 126,559 tokens out, 2,389,958 cache read, 143,992 cache write.
- edit: 2 calls, 6 tokens in, 14,926 tokens out, 62,784 cache read, 130,254 cache write.

Non cached input for the whole week is 538 tokens against 2.45 million cache read tokens. The contract schema preamble gets written to a one hour cache on the first call of a run and read back at ten percent of input rate on every call after, which is most of why the week costs two dollars and not twenty. Source: `docs/metrics/cost_table.md`, section 1 and section 4.

## Router table cost against CLI reported cost

Across the whole three week store, router table USD totals $5.067601, which includes a third analyst question recorded live after the sample run, and CLI reported USD totals $5.7556, a figure measured before that third question and carried forward as a declared constant, a ratio of 1.1358. Including the stability second opinion and the model swap, which run into scratch copies outside the store, the live run spent $5.4664 by the table and $6.69 by the CLI, a ratio of 1.2238. Source: `docs/metrics/cost_table.md`, section 5, and `docs/metrics/metrics.json`, `cost_two_ways`.

## KPIs

The baseline is what the product team knows today without this running, whatever reaches them through an account manager, and the measure is the delta after.

- **Cost per digest run.** Captured as `usage.total.cost_usd` in the run manifest, summed for the week in `week_summary.json`. Measured across the three weeks: $2.27, $1.03, $0.95, ingest and build together. Source: `docs/metrics/cost_table.md`, section 5 and KPI section.
- **Claims captured and claims rejected per run, with the rejection reasons.** Captured as `counts.claims_verified`, `counts.claims_rejected` and the `rejected_by_reason` block in the run manifest. Measured: 55 verified, 0 rejected across fifteen ingest runs, all five rejection reasons at zero. Source: `docs/metrics/cost_table.md`, KPI section, and `docs/metrics/metrics.json`, `three_week_totals`.
- **Themes touched per digest, appended against newly opened.** Captured as `counts.themes_appended` and `counts.themes_opened` in the run manifest. Measured: 0 appended and 10 opened in week 37, 7 appended and 1 opened in week 38, 8 appended and 0 opened in week 39. A healthy store appends more than it opens once it has history, and this store crosses over in its second week. Source: `docs/metrics/cost_table.md`, KPI section.
- **Product team actions taken, captured as approved themes filed to the backlog.** Captured as `counts.issues_filed` in the run manifest, with proposal files written to the proposals directory as the leading indicator. Measured: 15 proposal files across three weeks, one approval exercised as a dry run, 0 issues filed, because filing is gated behind an explicit approval flag and nobody has given it one yet. This is the outcome metric, and the only one of the four that says the digest actually changed anything. Source: `docs/metrics/cost_table.md`, KPI section, and `docs/metrics/metrics.json`, `three_week_totals`.
