# Walkthrough

This is the script for the recording. About three minutes, four beats, no slides and no preamble. The repository explains itself; the recording exists so someone can see it work without reading Python. Every command runs from the root of the code repository with the store beside it at `../bi-theme-digest-store`, and every one of them runs in replay mode, so there is no network call and nothing to configure.

Recording: PASTE THE RECORDING LOCATION HERE.

## Beat 1: run it

```
make demo
```

Talk over the output: fifteen nightly ingest runs and three weekly builds, replayed from recorded model responses, about sixteen seconds, zero network calls, and the result is byte identical to what is committed.

Then open the digest:

`../bi-theme-digest-store/digests/2026-W37.md`

Show the run line at the top of the page, which reads 25 sources read (14 calls, 11 cases), 4 private comments withheld, 5 PII redactions, 27 claims verified, 0 rejected, 0 themes appended, 10 opened, cost $2.27 for the week. Then open `../bi-theme-digest-store/digests/2026-W37.html` for two seconds so the page version is on screen once.

## Beat 2: take one sentence and resolve it

In `../bi-theme-digest-store/digests/2026-W37.md`, theme 1, read the first evidence line out loud:

> "There is a problem in the output that we have been working around since the spring though, and the board has now noticed it. Every renewal statement we send out is missing the balance that carried over from the previous period, so the invoice total reads far higher than it should." : Great Lakes Museum Alliance (customer), call 7782934451002 at 11:03, Rhonda Calloway [03a7ca4ae6d8]

Then follow it down, two commands:

```
grep 03a7ca4ae6d8 ../bi-theme-digest-store/evidence/claims/2026-09-08T06:00Z.jsonl | python -m json.tool
```

Point at `source_ref`: call `7782934451002`, speaker `4521`, window 663288 ms to 722760 ms, and `speaker_side` is `client`, which code derived from the connector's participant side and not from the model.

```
grep -c "Every renewal statement we send out is missing the balance" data/mock/traps/gong/calls/7782934451002.json
```

Then open `data/mock/traps/gong/calls/7782934451002.json` and find the turn starting at 663288 ms. Say the rule once: the quote has to be an exact substring of that window or the claim is rejected, code checks it, and 663288 ms is the 11:03 the digest printed.

## Beat 3: what the agent was not allowed to see

```
grep '"action": "withhold"' ../bi-theme-digest-store/runs/2026-09-10T06:00Z/run.log.jsonl
```

Three lines. Point at the second one, target `5008W00002aQpLrQAK`, `"detail": {"count": 1, "reason": "IsPublished false, never returned by the query"}`. The withholding happened at the query, in the connector, so the comment never existed as far as the reader agent was concerned, and the log records the count and never the value.

Then show it is actually gone, run from the store repository root:

```
grep -rl "this account is a churn risk if the invoice thing drags on" --exclude-dir=.git .
```

Zero hits, exit 1. Say the number: 4 private comments withheld in this week, 10 across the three weeks, and the digest run line carries it.

## Beat 4: the gate

```
python -m digest approve --theme THEME-0002 --dry-run --mode replay --repo OWNER/product-feedback
```

It prints the issue title, the body and the evidence table, and files nothing. Show the proposal the editor wrote sitting unapproved at `../bi-theme-digest-store/proposals/2026-W37/THEME-0002.md`.

```
python -m digest approve --theme THEME-0002 --mode replay --repo OWNER/product-feedback
```

Exits 4, refused, `--yes` required. Then run it again with `--yes` against a repository you own and show the issue appear. Last line to say: the agent decided what was worth filing and wrote the proposal, and a person filed it.
