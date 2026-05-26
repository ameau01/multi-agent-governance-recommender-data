#!/usr/bin/env bash
# ============================================================
# 03_validate.sh — Phase 3: QA validation
#
# Runs contract-layer (Pydantic schema, record counts, timestamp continuity,
# topology consistency, Terraform parse) and semantic-layer (pattern frequency,
# weekend behavior, Pass 2 invariance, correlation timing/magnitude, no
# spurious correlations) checks against every generated scenario folder.
#
# Model:        none (deterministic checks, no LLM)
# Scenarios:    18 (all)
# Cost:         $0
# Wall time:    ~1 min
#
# RESUMABLE: each scenario's qa_report.json is checkpointed. Re-running
# skips scenarios that have a passing report.
#
# REQUIRES: Phase 02 (Pass 2) must have completed first — validate reads
# the produced `scenarios/NN/*.json` files plus `intermediates/NN/pass1.json`
# (for the Pass 2 invariance check).
#
# Usage:
#   bin/03_validate.sh               Interactive, with confirmation prompt
#   bin/03_validate.sh --yes         Skip the confirmation prompt
#   bin/03_validate.sh --force       Re-validate every scenario (ignore prior reports)
# ============================================================

set -euo pipefail

YES_FLAG=""; FORCE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --yes)   YES_FLAG="--yes" ;;
    --force) FORCE_FLAG="--force" ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================================"
echo "  Phase 03 — QA validation (contract + semantic)"
echo "============================================================"

uv run python -m generator.cli validate-all $YES_FLAG $FORCE_FLAG
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "------------------------------------------------------------"
  echo "Phase 03 complete. Review hints:"
  echo "  ls -la scenarios/*/                              # all 7 files per scenario?"
  echo "  cat intermediates/*/qa_report.json | jq '.overall'"
  echo "  cat intermediates/*/qa_report.json | jq 'select(.overall==\"fail\")'"
  echo ""
  echo "If any scenarios failed QA, regenerate them with:"
  echo "  make pass1 SCENARIO=NN && make pass2 SCENARIO=NN"
  echo "  then re-run bin/03_validate.sh"
  echo ""
  echo "Next step:  bin/04_smoke_test.sh"
fi

exit $EXIT_CODE
