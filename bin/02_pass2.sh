#!/usr/bin/env bash
# ============================================================
# 02_pass2.sh — Phase 2: Cross-tier correlation injection
#
# For the ~6 scenarios with cross-tier correlations, reads Pass 1 output and
# surgically modifies the affected metrics while preserving everything else
# bit-exact. Skips correlation-free scenarios (pass-through copy).
#
# Model:        Claude Sonnet 4.6
# Scenarios:    6 of 18 (correlation scenarios only)
# Cost:         ~$54 interactive, ~$27 batch
# Wall time:    ~8 min interactive, ~20 min batch
#
# RESUMABLE: each scenario's pass2.json is checkpointed atomically after
# the LLM call returns. Re-running skips completed scenarios.
#
# REQUIRES: Phase 01 (Pass 1) must have completed first — pass2 reads
# `intermediates/NN/pass1.json` as input.
#
# Usage:
#   bin/02_pass2.sh                  Interactive, with confirmation prompt
#   bin/02_pass2.sh --batch          Anthropic Batches API (50% cost, async)
#   bin/02_pass2.sh --yes            Skip the confirmation prompt
#   bin/02_pass2.sh --force          Ignore existing checkpoints; re-run all
# ============================================================

set -euo pipefail

BATCH_FLAG=""; YES_FLAG=""; FORCE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --batch) BATCH_FLAG="--batch" ;;
    --yes)   YES_FLAG="--yes" ;;
    --force) FORCE_FLAG="--force" ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "============================================================"
echo "  Phase 02 — Pass 2 (cross-tier correlation injection)"
echo "============================================================"

uv run python -m generator.cli pass2-all $BATCH_FLAG $YES_FLAG $FORCE_FLAG
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "------------------------------------------------------------"
  echo "Phase 02 complete. Review hints:"
  echo "  ls -la intermediates/*/pass2.json"
  echo "  ls -la scenarios/*/correlation_evidence.json"
  echo "  # Only correlation-affected tiers should differ:"
  echo "  diff <(jq .Compute_Metrics[0:3] intermediates/07/pass1.json) \\"
  echo "       <(jq .Compute_Metrics[0:3] intermediates/07/pass2.json)"
  echo ""
  echo "Next step:  bin/03_validate.sh"
fi

exit $EXIT_CODE
