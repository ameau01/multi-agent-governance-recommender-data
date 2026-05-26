#!/usr/bin/env bash
# ============================================================
# 01_pass1.sh — Phase 1: Base telemetry generation
#
# Generates the four `*_telemetry.json` tier arrays for every scenario via
# Pass 1 LLM synthesis. No cross-tier correlation in this pass.
#
# Model:        Claude Sonnet 4.6
# Scenarios:    18 (all)
# Cost:         ~$101 interactive, ~$50 batch
# Wall time:    ~15 min interactive, ~30 min batch
#
# RESUMABLE: each scenario's pass1.json is checkpointed atomically after
# the LLM call returns. Re-running this script after a Mac sleep, Ctrl-C,
# or network blip will skip completed scenarios and pay only for the rest.
#
# Usage:
#   bin/01_pass1.sh                  Interactive, with confirmation prompt
#   bin/01_pass1.sh --batch          Anthropic Batches API (50% cost, async)
#   bin/01_pass1.sh --yes            Skip the confirmation prompt
#   bin/01_pass1.sh --force          Ignore existing checkpoints; re-run all
#   bin/01_pass1.sh --yes --batch    Unattended batch mode
# ============================================================

set -euo pipefail

BATCH_FLAG=""; YES_FLAG=""; FORCE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --batch) BATCH_FLAG="--batch" ;;
    --yes)   YES_FLAG="--yes" ;;
    --force) FORCE_FLAG="--force" ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Make `generator` and `qa` importable from src/ as top-level packages
# (defensive — works even if `uv sync` hasn't been re-run after the
# pyproject.toml src-layout fix).
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================================"
echo "  Phase 01 — Pass 1 (base telemetry generation)"
echo "============================================================"

uv run python -m generator.cli pass1-all $BATCH_FLAG $YES_FLAG $FORCE_FLAG
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "------------------------------------------------------------"
  echo "Phase 01 complete. Review hints:"
  echo "  ls -la intermediates/*/pass1.json"
  echo "  head -50 intermediates/01/pass1.json    # spot-check Scenario 01"
  echo "  head -50 intermediates/07/pass1.json    # spot-check Scenario 07"
  echo ""
  echo "Next step:  bin/02_pass2.sh"
fi

exit $EXIT_CODE
