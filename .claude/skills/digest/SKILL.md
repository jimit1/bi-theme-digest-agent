---
name: digest
description: Run the BI theme digest pipeline from Claude Code, either the full demo or one of the five verbs directly.
---

# Running the digest pipeline

This project has one entry point and five verbs, plus a `demo` that runs the whole thing
end to end. Everything defaults to `--mode replay`, which reads and writes only the
committed mock corpus and never calls a live model, so it costs nothing and always gives
the same answer.

## The one command a new reader needs

```
make demo
```

This runs `python -m digest demo --mode replay`, which ingests all fifteen mock days in
order, then builds three weeks of digests (`2026-W37`, `2026-W38`, `2026-W39`), then prints
where the outputs landed. Read that printed path; the digests are written under
`../bi-theme-digest-store/digests/` relative to this repository, one markdown file and one
self-contained HTML file per week.

## The five verbs directly

```
python -m digest ingest --day 2026-09-08         # connectors, scrub, extract, verify, enrich
python -m digest ingest --since-watermark        # what the nightly workflow actually calls
python -m digest build  --week 2026-W37          # editor, score, digest, HTML, commit, propose
python -m digest eval                            # the golden set
python -m digest ask    "why does the renewal credit issue matter"
python -m digest approve --theme THEME-0003 --yes  # human gate, files a GitHub issue
```

## Replay versus live

- `--mode replay` (the default): reads recorded model responses from the store's
  `runs/<run_id>/responses/` directory. No network call, no API key needed, fully
  reproducible. This is what CI and the demo use.
- `--mode record`: makes real model calls and writes the responses to disk for later
  replay. Use this once to refresh the recorded corpus after a prompt change.
- `--mode live`: makes real model calls every time, for a real production run. Needs
  model credentials configured for whichever provider `config/models.yaml` names.

Use `make demo-live` to run the demo in live mode instead of replay, and `make swap-models
MODELS=config/models.cheap.yaml` to see the same run against a cheaper tier map.

## Where things land

- Verified claims, themes and digests all live in the sibling repository
  `bi-theme-digest-store`, never in this one. This repository contains no pipeline output.
- Run logs and recorded responses live under `runs/<run_id>/` in the store.
- File proposals for the human gate land under `proposals/<week>/` in the store, with
  `status: proposed` until a human runs `approve --yes`.

## Other useful targets

- `make setup` creates the virtualenv and installs the package.
- `make data` regenerates the non-trap mock corpus from `data/mock/seed_spec.yaml`.
- `make test` runs the pytest suite.
- `make clean-store` restores the store repository to its committed state; it warns before
  it runs because it discards anything uncommitted there.
