#!/usr/bin/env bash
# ============================================================
# run_phase.sh — Run a single phase across all scenarios.
#
# Wrapper around the CLI's phase-level commands. Adds nicer help text and
# defaults to interactive confirmation (no --yes).
#
# Usage:
#   bin/run_phase.sh PHASE [--batch]
#
# Phases:
#   pass1        Pass 1 telemetry generation (18 scenarios, Sonnet 4.6)
#   pass2        Pass 2 correlation injection (6 scenarios, Sonnet 4.6)
#   validate     QA validator across all 18 (no LLM)
#   smoke-test   Smoke test on all 18 (Opus 4.6 + Haiku 4.5 judge)
#
# Examples:
#   bin/run_phase.sh pass1                Pass 1 in interactive mode
#   bin/run_phase.sh pass2 --batch        Pass 2 via Anthropic Batches API
#   bin/run_phase.sh smoke-test           Smoke test in interactive mode
# ============================================================

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 PHASE [--batch]"
  echo ""
  echo "Phases: pass1 | pass2 | validate | smoke-test"
  exit 1
fi

PHASE="$1"
shift
BATCH_FLAG=""
if [[ "${1:-}" == "--batch" ]]; then
  BATCH_FLAG="--batch"
fi

case "$PHASE" in
  pass1|pass2|validate|smoke-test)
    CMD="${PHASE}-all"
    ;;
  *)
    echo "Unknown phase: $PHASE"
    echo "Valid phases: pass1 | pass2 | validate | smoke-test"
    exit 2
    ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Running phase: $PHASE"
[[ -n "$BATCH_FLAG" ]] && echo "Mode: BATCH (50% pricing, async)"
echo ""

exec uv run python -m generator.cli "$CMD" $BATCH_FLAG
