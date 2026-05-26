#!/usr/bin/env bash
# ============================================================
# run_overnight_sweep.sh — Run the full data-gen pipeline across
# a list of scenarios. Designed for unattended overnight runs.
#
# For each scenario:
#   - Skips if intermediates/NN/smoke_test_judge.json already exists
#     (i.e. all 5 phases previously completed for that scenario).
#   - Otherwise invokes bin/run_scenario.sh which runs phases
#     pass1 → pass2 → validate → smoke-test → smoke-test-judge,
#     short-circuiting on any phase failure.
#
# Per-scenario failures do NOT stop the sweep — the loop continues
# to the next scenario, and the failure is logged in the summary.
#
# Usage:
#   bin/run_overnight_sweep.sh                       Run default 16 scenarios.
#   bin/run_overnight_sweep.sh --scenarios "02 05 13"
#                                                    Run only the listed scenarios.
#   bin/run_overnight_sweep.sh --dry-run             Print plan, run nothing.
#   bin/run_overnight_sweep.sh -h | --help           This message.
#
# Wrap with nohup + caffeinate for true unattended runs (macOS):
#   nohup caffeinate -i -d -s bin/run_overnight_sweep.sh \
#         > logs/overnight_sweep_v1.log 2>&1 &
#
# Or run interactive (foreground, with live output):
#   bin/run_overnight_sweep.sh
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Default scenarios: everything except 01 and 10 (already complete in this repo)
DEFAULT_SCENARIOS="02 03 04 05 06 07 08 09 11 12 13 14 15 16 17 18"

SCENARIOS_ARG="$DEFAULT_SCENARIOS"
DRY_RUN=0

show_help() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --scenarios)
      [[ $# -ge 2 ]] || { echo "ERROR: --scenarios needs an argument" >&2; exit 2; }
      SCENARIOS_ARG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Convert string "02 03 04" into an array
read -ra SCENARIOS <<< "$SCENARIOS_ARG"

SWEEP_START=$(date +%s)

echo "=========================================="
echo "  Overnight sweep started: $(date)"
echo "  Scenarios (${#SCENARIOS[@]}): ${SCENARIOS[*]}"
echo "  Dry run:  $([[ "$DRY_RUN" == "1" ]] && echo yes || echo no)"
echo "=========================================="

# Sanity-check that bin/run_scenario.sh exists and is executable
if [[ ! -x bin/run_scenario.sh ]]; then
  echo "ERROR: bin/run_scenario.sh not found or not executable" >&2
  exit 2
fi

COMPLETED=()
FAILED=()
SKIPPED=()

for sid in "${SCENARIOS[@]}"; do
  echo ""
  echo "------------------------------------------"
  echo "  SCENARIO $sid — start: $(date)"
  echo "------------------------------------------"

  # Skip if smoke_test_judge.json already exists (all 5 phases done previously)
  if [[ -f "intermediates/$sid/smoke_test_judge.json" ]]; then
    echo "  - already complete (smoke_test_judge.json present) - skipping"
    SKIPPED+=("$sid")
    continue
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  [dry-run] would invoke: bin/run_scenario.sh $sid"
    COMPLETED+=("$sid (dry-run)")
    continue
  fi

  # Invoke per-scenario wrapper. Disable -e for this call only so a per-scenario
  # failure doesn't abort the whole sweep.
  set +e
  bin/run_scenario.sh "$sid"
  EXIT_CODE=$?
  set -e

  if [[ "$EXIT_CODE" -eq 0 ]]; then
    COMPLETED+=("$sid")
    echo "  PASS: $sid complete"
  else
    FAILED+=("$sid (exit $EXIT_CODE)")
    echo "  FAIL: $sid failed with exit $EXIT_CODE - continuing to next scenario"
  fi
done

SWEEP_END=$(date +%s)
TOTAL_SEC=$(( SWEEP_END - SWEEP_START ))
TOTAL_MIN=$(( TOTAL_SEC / 60 ))
TOTAL_HRS=$(( TOTAL_MIN / 60 ))
REM_MIN=$(( TOTAL_MIN % 60 ))

echo ""
echo "=========================================="
echo "  SWEEP COMPLETE: $(date)"
echo "  Total time: ${TOTAL_HRS}h ${REM_MIN}m (${TOTAL_SEC}s)"
echo "=========================================="
echo "  Completed (${#COMPLETED[@]}): ${COMPLETED[*]:-}"
echo "  Failed    (${#FAILED[@]}): ${FAILED[*]:-}"
echo "  Skipped   (${#SKIPPED[@]}): ${SKIPPED[*]:-}"

# Exit non-zero if anything failed, so caller can detect overall sweep status
if [[ "${#FAILED[@]}" -gt 0 ]]; then
  exit 1
fi
