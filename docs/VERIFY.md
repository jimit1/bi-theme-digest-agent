# Verify this prototype yourself

Everything below I ran myself, start to finish, from a clone that had never seen either repository before. I am writing down exactly what I typed and exactly what came back, so an independent person or agent can repeat it and know within a few minutes whether their result matches mine. Nothing here is a description of what should happen; it is a record of what did happen.

## 1. Prerequisites

You need `git`, Python 3.12 or newer, and `make`. Nothing else.

- No credentials of any kind. Nothing in this guide touches a real Gong account, a real Salesforce org, or an API key.
- No network access is needed once `make setup` has finished installing the Python dependencies. `make setup` itself calls `pip install`, which needs the network the first time it has to fetch a package rather than reuse one already on the machine. Every other command in this guide, including the full three week demo, runs in replay mode against recordings that are already inside the repositories, with no outbound call of any kind.

Check your Python version before anything else:

```
python3 --version
```

Expected: `Python 3.12` or higher. I ran this on `Python 3.14.3`.

## 2. Spin up

Clone the code and the store side by side, in one empty parent directory: the bi-theme-digest-agent and bi-theme-digest-store repositories under the jimit1 account. The store has to sit next to the code as `../bi-theme-digest-store`, which is the path every command in this repository defaults to.

```
git clone <bi-theme-digest-agent repository under the jimit1 account>
git clone <bi-theme-digest-store repository under the jimit1 account>
cd bi-theme-digest-agent
make setup
```

Expected, the last handful of lines:

```
Successfully installed annotated-types-0.8.0 anthropic-1.6.0 anyio-4.15.1 attrs-26.1.0 bi-theme-digest-agent-0.1.0 ...

[notice] A new release of pip is available: ...
[notice] To update, run: .../bi-theme-digest-agent/.venv/bin/python -m pip install --upgrade pip
```

The exact package versions and the pip notice text can drift over time; what has to be true is no error, and a line reading `Successfully installed ... bi-theme-digest-agent-0.1.0` somewhere near the end. On my machine this took about seven seconds.

## 3. Run the demo

```
make demo
```

This is a full replay of three weeks from an empty store, no network, no API key. Expected shape of the output, trimmed to the lines that matter:

```
fresh demo: replaying three weeks into .../bi-theme-digest-store-demo
  recordings come from .../bi-theme-digest-store, which is only read
  scaffold commit b48ad65 cloned, 20 recording directories restored

ingest 2026-09-07: 0 sources listed, 0 read, ... 0 claims extracted, 0 verified, 0 rejected (none), 0.9s
ingest 2026-09-08: 9 sources listed, 9 read, ... 11 claims extracted, 11 verified, 0 rejected (none), 1.0s
ingest 2026-09-09: 7 sources listed, 7 read, ... 7 claims extracted, 7 verified, 0 rejected (none), 1.0s
ingest 2026-09-10: 5 sources listed, 5 read, ... 5 claims extracted, 5 verified, 0 rejected (none), 0.9s
[... eleven more ingest lines, one per day, fifteen in total, every one reading "0 rejected (none)" ...]

build 2026-W37: 0 themes appended, 10 opened, 0 quiet (0 before), 0 stale (0 before), 6 proposals, cost $1.2187, 1.0s
  .../bi-theme-digest-store-demo/digests/2026-W37.md
  .../bi-theme-digest-store-demo/digests/2026-W37.html
[... ten "opened THEME-000n ..." lines ...]

build 2026-W38: 7 themes appended, 1 opened, 0 quiet (0 before), 0 stale (0 before), 5 proposals, cost $0.4383, 1.2s
  .../bi-theme-digest-store-demo/digests/2026-W38.md
  .../bi-theme-digest-store-demo/digests/2026-W38.html

build 2026-W39: 8 themes appended, 0 opened, 3 quiet (3 before), 3 stale (3 before), 4 proposals, cost $0.4586, 1.1s
  .../bi-theme-digest-store-demo/digests/2026-W39.md
  .../bi-theme-digest-store-demo/digests/2026-W39.html

demo complete in 18.6s, mode replay, from an empty store
  .../bi-theme-digest-store-demo/digests/2026-W37.md
  .../bi-theme-digest-store-demo/digests/2026-W38.md
  .../bi-theme-digest-store-demo/digests/2026-W39.md

eval: 18 of 18 assertions passed

.../bi-theme-digest-store-demo, 19 commits:
  6275e8d run 2026-09-28T07:00Z: build 2026-W39 digest, 8 themes appended, 0 opened
  94836d2 run 2026-09-21T07:00Z: build 2026-W38 digest, 7 themes appended, 1 opened
  9b44dba run 2026-09-14T07:00Z: build 2026-W37 digest, 0 themes appended, 10 opened
  [... fifteen ingest commits, one per day ...]
  b48ad65 scaffold: empty context store, ROUTER.md and the two index files
```

Numbers that must match exactly on any machine: 15 ingest lines, 0 rejected on every one, the three build lines with 10/1/0 opened, `18 of 18 assertions passed`, and 19 commits ending in the scaffold commit `b48ad65`. The seven digit commit hashes above it will be different on your run, because a commit's hash depends on the timestamp it was made at, and that timestamp is your clock, not a recording. Timing: about eighteen to twenty seconds on my machine, the second run a little faster than the first once the interpreter's caches are warm.

## 4. Open the outputs

The HTML digest is a plain file. It opens straight from the filesystem, no server, in any browser. On macOS:

```
open ../bi-theme-digest-store-demo/digests/2026-W37.html
```

On Linux, `xdg-open` in place of `open`; on Windows, double click the file, or `start` from a command prompt. Everywhere else, just open the path in a browser's file picker.

Click any evidence line. It expands in place to the source moment: the call or case comment it came from, the speaker, and the sentence itself highlighted inside the couple of sentences around it, so you can see it was not lifted out of context. Click "Why this score" under a theme. It expands to the five weighted terms, each with its numbers filled in and its arithmetic shown, ending in the same score printed at the top of the theme.

The markdown digest sits beside it at `digests/2026-W37.md`, same content, plain text. `themes/_INDEX.md` is the one table of every theme, its score, its status and the run it last changed on. `themes/THEME-0002.md` is one theme's full record: its score inputs, its rationale, and the exact list of claim ids that back it.

The audit log is one JSON object per line, one file per run, at `runs/<run_id>/run.log.jsonl`. A line looks like this:

```
{"schema_version": "1.0.0", "ts": "...", "run_id": "2026-09-21T06:00Z", "agent": "scrubber", "action": "scrub", "stage": "scrub", "target": "500000000000000016", "model_tier": null, "model_id": null, "prompt_hash": null, "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0, "outcome": "ok", "detail": {"EMAIL": 0, "PHONE": 0, "ADDRESS": 0, "NAME": 0}}
```

`git log` inside the store repository is the audit trail at the level of a run rather than a field: every ingest and every build is one commit, in order, which is what section 3 above already printed.

## 5. Trace one claim by hand

Pick a claim id off a digest and follow it to the word it came from. I used the first evidence line under theme one of the 2026-W37 digest, claim id `03a7ca4ae6d8`, which the digest says is call `7782934451002` at `11:03`.

```
grep 03a7ca4ae6d8 ../bi-theme-digest-store-demo/evidence/claims/2026-09-08T06:00Z.jsonl | python3 -m json.tool
```

Expected, the fields that matter:

```
"claim_id": "03a7ca4ae6d8",
"source_ref": {
    "call_id": "7782934451002",
    "speaker_id": "4521",
    "speaker_name": "Rhonda Calloway",
    "start_ms": 663288,
    "end_ms": 722760
},
"speaker_side": "client",
"verbatim": "There is a problem in the output that we have been working around since the spring though, and the board has now noticed it. Every renewal statement we send out is missing the balance that carried over from the previous period, so the invoice total reads far higher than it should."
```

663288 milliseconds is 11 minutes 3 seconds, the moment the digest printed. Now open the mock call and find that window:

```
python3 -c "
import json
d = json.load(open('data/mock/traps/gong/calls/7782934451002.json'))
for turn in d['transcript']['transcript']:
    if turn['speakerId'] == '4521':
        for s in turn['sentences']:
            if s['start'] >= 663288 and s['end'] <= 722760:
                print(s['start'], s['end'], s['text'])
"
```

Expected, among the printed sentences:

```
663288 681342 The preparation is the same. There is a problem in the output that we have been working around since the spring though, and the board has now noticed it.
681342 699750 Every renewal statement we send out is missing the balance that carried over from the previous period, so the invoice total reads far higher than it should.
```

The claim's `verbatim` is the second half of the first sentence joined to the whole of the second, word for word, with no paraphrase and nothing added. That join is exactly what code checks before a claim is allowed to exist: I confirmed with a three line script that the `verbatim` string is an exact Python substring of those two sentences joined with a single space, which is a `True`. This is the check the codebase calls citation verification; a claim that fails it is rejected before it ever reaches a theme.

## 6. Use it

```
make eval
```

Expected, the last line: `18 of 18 assertions passed.`

```
make ask Q="why does the renewal invoice issue matter"
```

Expected, the answer I got back, word for word:

```
It matters because members get billed too much and staff have to fix it by hand. Prairie Land Trust Council says chapters that upgrade partway through the year are billed the whole annual figure again with nothing knocked off, and every invoice is corrected manually (THEME-0002, 306b8bbab997; THEME-0002, b624be88b791). Great Lakes Museum Alliance says renewal statements are missing the balance carried over from the previous period, so the invoice total reads far higher than it should, and the board has noticed (THEME-0002, 03a7ca4ae6d8). The same account says the credit line for the partial year adjustment is missing and finance chases it every cycle (THEME-0002, 260d27e4dad0; THEME-0002, 85de85afeea8). So the cost is wrong bills to members, repeat finance work each cycle, and visibility at the board level.
```

Now ask something the store has no evidence for:

```
make ask Q="how many seats does the mobile app licence include next year"
```

Expected, the decline, word for word:

```
I can't answer this. The themes available cover renewal billing that misses prior-period credits and mid-year upgrades, and report exports that cut off above a row threshold. Neither covers mobile app licensing or seat counts.
  unsupported: The theme store has nothing on mobile app licence seat counts.
```

```
make swap-models
```

Expected, all three lines:

```
cost:    reference $1.2187, alternate $0.2831 (23.2 percent of reference)
eval:    reference 16 of 16 assertions, alternate 16 of 16
overlap: claim co-assignment jaccard 1.000 (with theme ids 0.174), 10 themes against 10, top three CHANGED (['THEME-0002', 'THEME-0001', 'THEME-0006'] vs ['THEME-0007', 'THEME-0001', 'THEME-0003'])
```

The two runs group every claim the same way, jaccard 1.000, at 23 percent of the reference cost. The theme ids on the top three differ because ids are handed out in the order the editor happens to open themes in, which is exactly the labelling-versus-ranking distinction the README calls out; the claim sets underneath are identical.

```
make approve-dry THEME=THEME-0002
```

Expected, the issue title, then the full body, filing nothing:

```
THEME-0002: Renewal billing omits prior-period credits and does not prorate mid-year upgrades
# Renewal billing omits prior-period credits and does not prorate mid-year upgrades
...
Filed from theme digest 2026-W37, run 2026-09-14T07:00Z, approved by a human with `digest approve --yes`.
```

Now the important one. `make approve` in this Makefile is not the same shape as `make approve-dry`. Look at the two targets:

```
approve-dry:
	$(PY) -m digest approve --theme $(THEME) --repo $(REPO) --dry-run

approve:
	$(PY) -m digest approve --theme $(THEME) --yes --repo $(REPO)
```

`make approve` already carries `--yes`, and `REPO` defaults to the real `bi-theme-digest-agent` repository under the jimit1 account. There is no confirmation step between typing `make approve THEME=...` and a real, public GitHub issue being filed with `gh`, against whatever account your `gh` is logged into. This is the human gate the governance doc describes, and it does exactly what it says: it treats `--yes` as the human's word, no more prompting after that. Do not run bare `make approve` to see what the gate does; run the command below instead, which shows the refusal without touching any repository:

```
.venv/bin/python -m digest approve --theme THEME-0002 --repo OWNER/product-feedback
```

Expected:

```
refused: --yes required
```

and the process exits with status 4. That is the whole demonstration: the gate refuses without `--yes`, and it will only ever file something once a human has both proposed nothing, reviewed a proposal the editor already wrote, and typed `--yes` themselves against a repository they actually intend to file into.

```
make test
```

Expected, the last line: `531 passed` (mine also printed 44 deprecation warnings from the corpus generator, which is noise, not a failure).

```
make demo-inplace
```

Run against the real committed store rather than a scratch copy, every ingest day is already behind the watermark and every week already built, so this is a no-op:

```
ingest 2026-09-07: already ingested (watermark 2026-09-25), nothing to do
[... one such line per ingest day ...]
build 2026-W37: already built (run 2026-09-14T07:00Z), nothing to do
build 2026-W38: already built (run 2026-09-21T07:00Z), nothing to do
build 2026-W39: already built (run 2026-09-28T07:00Z), nothing to do

demo complete in 0.0s, mode replay
Digests landed in ../bi-theme-digest-store/digests/
```

`make demo-live` is the same three week pipeline with `--mode live` instead of `--mode replay`, so it calls the model provider for real. It needs the Claude CLI signed into a seat rather than an API key, and it costs real money: about 4 to 6 USD for the full three weeks by the pricing table, depending on caching. I did not run it for this guide; it makes live model calls, and this guide is meant to be reproducible for free.

## 7. Governance checks you can run

Four of the seven controls in `docs/GOVERNANCE.md`, run against the store this demo produced.

Withheld comment count:

```
grep -h '"action": "withhold"' ../bi-theme-digest-store/runs/*/run.log.jsonl | wc -l
```

Expected: `10`.

PII grep, checking that a planted name never survives anywhere in the store:

```
grep -rl "Harold Pemberton-Vance" --exclude-dir=.git ../bi-theme-digest-store
```

Expected: no output, and the command exits 1.

Editor tool boundary, four reads and no write:

```
grep -n "def read_theme_index\|def read_theme\|def list_run_claims\|def read_account\|def write" src/digest/agents/editor/tools.py
```

Expected: four lines, `read_theme_index`, `read_theme`, `list_run_claims`, `read_account`. `def write` matches nothing.

Dash check, confirming neither an em dash nor an en dash appears anywhere in the code or the docs:

```
grep -rlP '[\x{2013}\x{2014}]' --exclude-dir=.git --exclude-dir=.venv .
```

Expected: no output.

## 8. What good looks like

| Measure | Expected |
| --- | --- |
| Claims verified across all three weeks | 55 |
| Claims rejected | 0 |
| Themes by week 2026-W39 | 11 |
| Themes opened in 2026-W37 | 10 |
| Themes opened in 2026-W38 | 1 |
| Themes opened in 2026-W39 | 0 (3 quiet, 3 stale) |
| Eval | 18 of 18 |
| Tests | 531 passed |

If any of these numbers differ on your run, something in your environment produced a different result than mine, and that difference is worth chasing before trusting the rest of the output.

## 9. The recorded walkthrough

`walkthrough.md` in the root of this repository is the script for a three minute recording: four beats, the exact command for each, and what to say over it. It covers the same ground as this guide in less depth and less detail; use it if you want to watch the prototype work rather than run every step yourself.
