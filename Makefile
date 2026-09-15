PY ?= .venv/bin/python
MODELS ?= config/models.cheap.yaml
REPO ?= jimit1/bi-theme-digest-agent

.PHONY: approve-dry setup data demo demo-inplace demo-live eval swap-models test ask approve clean-store

setup:
	@test -x .venv/bin/python || python3 -m venv .venv
	$(PY) -m pip install -e ".[dev]"

data:
	$(PY) tools/generate_corpus.py --spec data/mock/seed_spec.yaml --out data/mock

demo:
	$(PY) -m digest demo --mode replay --fresh

demo-inplace:
	$(PY) -m digest demo --mode replay
	@echo "Digests landed in ../bi-theme-digest-store/digests/"

demo-live:
	$(PY) -m digest demo --mode live

eval:
	$(PY) -m digest eval

swap-models:
	$(PY) -m digest swap --models $(MODELS) --week 2026-W37

test:
	$(PY) -m pytest -q

ask:
	$(PY) -m digest ask "$(Q)"

approve-dry:
	$(PY) -m digest approve --theme $(THEME) --repo $(REPO) --dry-run

approve:
	$(PY) -m digest approve --theme $(THEME) --yes --repo $(REPO)

clean-store:
	@echo "WARNING: this restores ../bi-theme-digest-store to its committed state and deletes untracked files in it."
	git -C ../bi-theme-digest-store checkout -- .
	git -C ../bi-theme-digest-store clean -fd
