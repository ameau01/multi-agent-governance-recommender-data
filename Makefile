# cloud-governance-data-gen — common operations
# ----------------------------------------------------------
# Quick reference (organized by use case):
#
# PRIMARY PATH — Numbered per-phase scripts (RESUMABLE, manually triggered):
#
#   make 01-pass1                 Phase 1: Sonnet base telemetry (~$101 / $50 batch)
#   make 02-pass2                 Phase 2: Sonnet correlation injection (~$54 / $27 batch)
#   make 03-validate              Phase 3: QA validator (no LLM)
#   make 04-smoke-test            Phase 4: Opus recommendation (~$1.44 / $0.72 batch)
#   make 05-smoke-test-judge      Phase 5: Haiku judge on saved recommendations (~$0.01)
#
#   Run them in order, one at a time. Each script prints a banner, runs the
#   CLI with cost preview + confirmation, then shows review hints at the end.
#   All RESUMABLE — re-running a phase after an interrupt skips completed
#   scenarios and pays only for the rest.
#
#   Each script accepts --batch, --yes, --force flags. Pass with FLAGS=:
#       make 01-pass1 FLAGS="--batch --yes"
#
# ALTERNATIVE (all-in-one walk-through):
#   make oversight                Walk through all 5 phases with pauses between
#   make oversight-batch          Same, but with Batch API enabled
#
# RAW CLI (skip the bash wrappers):
#   make pass1-all                Same as bin/01_pass1.sh but no banner/review hints
#   make pass2-all                Same as bin/02_pass2.sh
#   make validate-all             Same as bin/03_validate.sh
#   make smoke-test-all           Same as bin/04_smoke_test.sh
#   make smoke-test-judge-all     Same as bin/05_smoke_test_judge.sh
#
# PER-SCENARIO (debugging / pilots):
#   make build SCENARIO=07            Build one scenario end-to-end
#   make pass1 SCENARIO=07            Phase B: regenerate Pass 1 only
#   make pass2 SCENARIO=07            Phase B: regenerate Pass 2 only
#   make smoke-test SCENARIO=07       Opus recommendation for one scenario
#   make smoke-test-judge SCENARIO=07 Haiku judge for one scenario
#   make validate SCENARIO=07         QA validator on one scenario
#
# SETUP & QUALITY:
#   make install                      uv sync — install all deps
#   make test                         pytest (skeleton import smoke test)
#   make lint                         ruff + mypy
#   make clean                        remove intermediates/ (debug-only output)

.PHONY: install \
        01-pass1 02-pass2 03-validate 04-smoke-test 05-smoke-test-judge \
        build build-all build-metadata build-terraform pass1 pass2 \
        smoke-test smoke-test-judge validate \
        pass1-all pass2-all smoke-test-all smoke-test-judge-all validate-all \
        pass1-all-batch pass2-all-batch smoke-test-all-batch smoke-test-judge-all-batch \
        oversight oversight-batch resume \
        test lint clean

# Default scenario for targets that take SCENARIO=NN
SCENARIO ?= 01
PYTHON   = uv run python

# ----------------------------------------------------------
# Setup
# ----------------------------------------------------------
install:
	uv sync --all-extras
	@echo "✓ Dependencies installed."

# ----------------------------------------------------------
# Primary path — Numbered per-phase scripts (RESUMABLE)
# Each script: banner + CLI (cost preview + confirmation) + review hints.
# Pass flags via FLAGS=:  make 01-pass1 FLAGS="--batch --yes"
# ----------------------------------------------------------
FLAGS ?=

01-pass1:
	@bash bin/01_pass1.sh $(FLAGS)

02-pass2:
	@bash bin/02_pass2.sh $(FLAGS)

03-validate:
	@bash bin/03_validate.sh $(FLAGS)

04-smoke-test:
	@bash bin/04_smoke_test.sh $(FLAGS)

05-smoke-test-judge:
	@bash bin/05_smoke_test_judge.sh $(FLAGS)

# ----------------------------------------------------------
# Alternative — All-in-one walk-through (legacy, optional)
# ----------------------------------------------------------
oversight:
	@bash bin/run_oversight.sh

oversight-batch:
	@bash bin/run_oversight.sh --batch

# ----------------------------------------------------------
# Phase-level commands (manual control across all scenarios)
# Each prints cost + time estimates, asks for confirmation, then runs.
# Add --yes to skip the confirmation prompt.
# Add --batch to use Anthropic Batches API at 50% cost.
# ----------------------------------------------------------
pass1-all:
	$(PYTHON) -m generator.cli pass1-all

pass2-all:
	$(PYTHON) -m generator.cli pass2-all

validate-all:
	$(PYTHON) -m generator.cli validate-all

smoke-test-all:
	$(PYTHON) -m generator.cli smoke-test-all

# Phase 5 — Haiku judge on saved Opus recommendations
smoke-test-judge-all:
	$(PYTHON) -m generator.cli smoke-test-judge-all

# Convenience variants with --batch pre-applied
pass1-all-batch:
	$(PYTHON) -m generator.cli pass1-all --batch

pass2-all-batch:
	$(PYTHON) -m generator.cli pass2-all --batch

smoke-test-all-batch:
	$(PYTHON) -m generator.cli smoke-test-all --batch

smoke-test-judge-all-batch:
	$(PYTHON) -m generator.cli smoke-test-judge-all --batch

# Resume — same as oversight, just makes intent explicit
resume:
	@bash bin/run_oversight.sh --resume

# ----------------------------------------------------------
# Per-scenario commands (debugging and pilots)
# ----------------------------------------------------------
build:
	$(PYTHON) -m generator.cli build $(SCENARIO)

build-all:
	$(PYTHON) -m generator.cli build-all

# Phase A — metadata + Terraform only, no telemetry (no LLM calls)
build-metadata:
	$(PYTHON) -m generator.cli build-metadata $(SCENARIO)

build-terraform:
	$(PYTHON) -m generator.cli build-terraform $(SCENARIO)

# Phase B — regenerate Pass 1 or Pass 2 for one scenario
pass1:
	$(PYTHON) -m generator.cli pass1 $(SCENARIO)

pass2:
	$(PYTHON) -m generator.cli pass2 $(SCENARIO)

# Per-scenario QA / smoke test
validate:
	$(PYTHON) -m generator.cli validate $(SCENARIO)

# Per-scenario smoke test (recommendation only — Opus call)
smoke-test:
	$(PYTHON) -m generator.cli smoke-test $(SCENARIO)

# Per-scenario judge (Haiku call on saved recommendation)
smoke-test-judge:
	$(PYTHON) -m generator.cli smoke-test-judge $(SCENARIO)

# Convenience: smoke test on the two pilot scenarios (01 and 07)
smoke-test-pilots:
	$(PYTHON) -m generator.cli smoke-test 01
	$(PYTHON) -m generator.cli smoke-test 07
	$(PYTHON) -m generator.cli smoke-test-judge 01
	$(PYTHON) -m generator.cli smoke-test-judge 07

# ----------------------------------------------------------
# Dev quality gates
# ----------------------------------------------------------
test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/
	uv run mypy src/

clean:
	rm -rf intermediates/
	@echo "✓ Removed intermediates/."
