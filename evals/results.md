# Golden set eval results

Date run: 2026-09-14.

Command: `python -m digest eval --mode replay`, run from the code repo with the store at
`../bi-theme-digest-store`, using the venv interpreter
`.venv/bin/python`. Replay mode, zero network calls,
zero live model spend.

Store commit sha (HEAD at run time): 65b7b0a25f3c2af17b78253337435f6818978d5f
("run 2026-09-28T08:00Z: ask, declined"). This is the consolidation regeneration: the same
replay from the scaffold commit and the run 3 recordings that B16's polish pass did, redone
on the scrubber fix in OD27, so the redaction counts in the run logs, the manifests, the
week summaries and the 2026-W37 run line now count each redaction once. 23 commits, the same
run for run history as before.

Run ids covered (every `runs/*` directory in the store, in order):
2026-09-07T06:00Z, 2026-09-08T06:00Z, 2026-09-09T06:00Z, 2026-09-10T06:00Z, 2026-09-11T06:00Z,
2026-09-14T06:00Z, 2026-09-14T07:00Z, 2026-09-15T06:00Z, 2026-09-16T06:00Z, 2026-09-17T06:00Z,
2026-09-18T06:00Z, 2026-09-21T06:00Z, 2026-09-21T07:00Z, 2026-09-22T06:00Z, 2026-09-23T06:00Z,
2026-09-24T06:00Z, 2026-09-25T06:00Z, 2026-09-28T07:00Z, 2026-09-28T08:00Z, 2026-09-28T09:00Z.
The last of these, 2026-09-28T09:00Z, is an approve dry run that filed nothing and left its
run log untracked, same as B16 left it.

Result: 18 of 18 assertions passed, exit code 0.

## Per assertion

| id | description | result | evidence |
| --- | --- | --- | --- |
| T1a | The renewal invoice claim from the Gong call 7782934451002 appears in the store, cited, attached to a theme, and quoted in the digest. | pass | theme THEME-0002, claim 03a7ca4ae6d8 |
| T1b | The renewal invoice claim from the Salesforce case 5008W00002aQpLrQAK appears in the store, cited, attached to a theme, and quoted in the digest. | pass | theme THEME-0002, claim 306b8bbab997 |
| T2a | The event check-in claim from the Gong call 7782934451118 appears in the store, cited, attached to a theme, and quoted in the digest. | pass | theme THEME-0006, claim dcb169d12187 |
| T2b | The attendee kiosk claim from the Gong call 7782934451207 appears in the store, cited, attached to a theme, and quoted in the digest. | pass | theme THEME-0006, claim ae96fcdf3b0a |
| T3 | The SCORM upload claim from the Gong call 7782934451311 appears in the store, cited, attached to a theme, and quoted in the digest, even though the account is a prospect. | pass | theme THEME-0009, claim 61d958ff323f |
| T4a | The private Salesforce case comment about churn risk never reaches any output. | pass | absent from every file in the store |
| T4c | The Momentive Software account executive line never becomes a client claim in any output. | pass | absent from every output; present only in the files that hold what the reader was shown |
| PII-email | The planted email never reaches the store. | pass | absent |
| PII-phone | The planted phone number never reaches the store. | pass | absent |
| PII-address | The planted street address never reaches the store. | pass | absent |
| PII-name | The planted donor name never reaches the store. | pass | absent |
| S1 | Every claim in the digest carries a citation, and every citation resolves to the mock source it names. | pass | 55 citations resolved |
| S2 | The two T1 claims, worded completely differently, are attached to exactly one theme between them. | pass | theme THEME-0002 from sources 5008W00002aQpLrQAK and 7782934451002 |
| S3 | The T2 theme carries both product names in its aliases, so the reconciliation is visible rather than implied. | pass | THEME-0006 aliases: event check-in, attendee kiosk |
| S4 | T3 is classified prospect and ranks below every customer backed theme of equal claim count, while still appearing in the digest. | pass | THEME-0009 scores 10 on 3 prospect claims |
| S5 | No planted PII value appears in any file in the store repository, including the audit log. | pass | 4 values, none present |
| S6 | A second build on the same input produces the same theme ids. | pass | 10 themes, identical ids on a genuine replayed rebuild |
| S7 | The stale evidence flag fires on the W39 digest for the one theme that received nothing for two weeks. | pass | THEME-0004, newest evidence 17 days old, past the fourteen day verify horizon |

## Must not appear: grep commands and results

Both sentences are planted on purpose in a raw fixture, which is what makes the control
demonstrable rather than asserted. The check that matters is whether either sentence ever
reaches an output: a claim, a theme, a digest, a proposal, or the audit log. `sources/` (the
scrubbed source document, kept exact per file_formats.md section 7) and `runs/*/responses*/`
(recorded model requests, which carry that same document as prompt text) hold what the reader
was shown, not what it produced, so a hit there is expected and is not a failure.

T4a, the private support comment about churn risk:

```
grep -rl "this account is a churn risk if the invoice thing drags on" --exclude-dir=.git .
```

Run from the store repository root. Zero hits, zero files, exit code 1 (no match). The
sentence is absent from the store entirely, including the raw fixture, because the Salesforce
connector filters `IsPublished: false` before the reader ever sees the comment.

T4c, the Momentive Software account executive line:

```
grep -rl "A lot of our customers ask for this." --exclude-dir=.git .
```

Run from the store repository root. 54 files matched: `sources/7782934451119.json` (the one
scrubbed source document that carries the call) and 53 files under `runs/*/responses*/`
(recorded requests whose prompt text repeats that same document). To check the part that
matters, the same grep with those two locations excluded:

```
grep -rl "A lot of our customers ask for this." --exclude-dir=.git . \
  | sed 's|^\./||' | grep -v '^sources/' | grep -vE '^runs/[^/]+/responses'
```

Zero hits, exit code 1. The sentence never appears in any claim, theme, digest, proposal, or
audit log file. It exists only in the document the reader was shown, exactly as designed.

## PII grep across the whole store repository

All four planted values, checked with no location excluded, because these must not exist
anywhere in the store at all, not even in the raw fixture:

```
grep -rl "dana.whitfield@example.net" --exclude-dir=.git .
grep -rl "(612) 555-0147" --exclude-dir=.git .
grep -rl "4821 Larkspur Lane, Duluth, MN 55803" --exclude-dir=.git .
grep -rl "Harold Pemberton-Vance" --exclude-dir=.git .
```

All four run from the store repository root. Every one returned zero hits, zero files, exit
code 1 (no match). None of the four planted values appears anywhere in the store repository,
sources and recorded responses included.

## Stability

From `runs/2026-09-14T07:00Z/manifest.json`, the build manifest for the 2026-W37 digest:

```
"stability": {"computed": true, "jaccard": 1.0, "top3_stable": true, "compared_run_id": "2026-09-14T07:00Z"}
```

Claim co-assignment jaccard: 1.000. Top three stable: true, by claim set. The same flag
compared by allocated theme id reads false, which is the number earlier drafts quoted. Both
are in `runs/2026-09-14T07:00Z/stability.json` alongside the manifest, because
RunManifest.stability is closed to four keys.

How this was measured, per B16's envelope: the build for week 2026-W37 was run a second time
with `--stability`, asking for a second live opinion from the synthesis model on the same
input claims. That second opinion was recorded into
`runs/2026-09-14T07:00Z/responses-stability` rather than written into the real store, so it
never touched the committed theme set. Jaccard compares which claims the two opinions grouped
into the same theme as each other, independent of what either opinion named the theme, so a
score of 1.000 means both opinions partitioned the week's claims into themes identically.
Top three stable now compares the set of claim ids each of the top three themes carries, and
the top three are the same three themes under different ids: the two opinions produced
identical claim sets in identical rank order, so that flag reads true. It read false before
because it compared allocated theme ids, and `store.allocate_theme_ids` hands out
THEME-000n in the editor's placeholder order, which on a cold start week is arbitrary: the
same three themes came back as THEME-0002, THEME-0001, THEME-0006 on one side and
THEME-0005, THEME-0001, THEME-0003 on the other. Both numbers are reported, the claim set
one as `top3_stable` and the id one as `top3_stable_by_id`, so the change is visible rather
than silent. The golden set expects the co-assignment metric at 1.0 and asks for it to be
reported whatever it is; both the earlier build (B16, run 3) and this replay agree on
1.000.
