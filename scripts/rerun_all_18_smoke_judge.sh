#!/usr/bin/env bash
# ============================================================
# rerun_all_18_smoke_judge.sh — Re-run smoke-test + smoke-test-judge
# for every one of the 18 scenarios, showing the per-scenario
# `bin/run_scenario.sh` output format you prefer.
#
# For each scenario this runs:
#   bin/run_scenario.sh NN --from smoke-test --to smoke-test-judge
#
# That regenerates the Opus recommendation (smoke_test.json) AND the
# Haiku judge verdict (smoke_test_judge.json), producing the familiar
# per-scenario banner:
#
#     ============================================================
#       Scenario: 07  (07.spec.yaml)
#       Phases:   smoke-test smoke-test-judge
#     ============================================================
#       ── Phase 4 (smoke-test) ──
#          ✓ complete (36s)
#       ── Phase 5 (smoke-test-judge) ──
#          ✓ complete (1s)
#
# After all 18 finish, this script ALSO runs the deterministic
# rubric scorer (no LLM, instant) to confirm 18/18 pass under the
# new scoring method — that's your HuggingFace ground-truth check.
#
# Per-scenario failures do NOT stop the sweep — the loop continues.
#
# Usage:
#   scripts/rerun_all_18_smoke_judge.sh
#       Re-run all 18 sequentially (~5-7 min, ~$3 Opus + ~$0.01 Haiku).
#   scripts/rerun_all_18_smoke_judge.sh --scenarios "07 11 15"
#       Re-run only the listed scenarios.
#   scripts/rerun_all_18_smoke_judge.sh --skip-deterministic
#       Skip the final deterministic-scorer confirmation pass.
#   scripts/rerun_all_18_smoke_judge.sh --dry-run
#       Print the plan, run nothing.
#   scripts/rerun_all_18_smoke_judge.sh -h | --help
#       This message.
#
# Wrap with nohup + caffeinate for unattended runs (macOS):
#   nohup caffeinate -i -d -s scripts/rerun_all_18_smoke_judge.sh \
#         > logs/rerun_all_18_$(date +%Y%m%d_%H%M%S).log 2>&1 &
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ALL_18="01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18"

EXPLICIT_SCENARIOS=""
SKIP_DETERMINISTIC=0
DRY_RUN=0

show_help() {
  sed -n '2,42p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --scenarios)
      [[ $# -ge 2 ]] || { echo "ERROR: --scenarios requires an argument" >&2; exit 2; }
      EXPLICIT_SCENARIOS="$2"; shift 2 ;;
    --skip-deterministic) SKIP_DETERMINISTIC=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Sanity
if [[ ! -x bin/run_scenario.sh ]]; then
  echo "ERROR: bin/run_scenario.sh not found or not executable" >&2
  exit 2
fi

# Build scenario list
if [[ -n "$EXPLICIT_SCENARIOS" ]]; then
  read -ra SCENARIOS <<< "$EXPLICIT_SCENARIOS"
else
  read -ra SCENARIOS <<< "$ALL_18"
fi

# ---- Plan banner ----
echo "=========================================="
echo "  Re-run smoke-test + smoke-test-judge for ${#SCENARIOS[@]} scenario(s)"
echo "  Started: $(date)"
echo "  Scenarios: ${SCENARIOS[*]}"
echo "  Dry run:   $([[ "$DRY_RUN" == "1" ]] && echo yes || echo no)"
[[ "$SKIP_DETERMINISTIC" == "1" ]] && echo "  Deterministic confirmation: SKIPPED"
echo "=========================================="

if [[ "$DRY_RUN" == "1" ]]; then
  for sid in "${SCENARIOS[@]}"; do
    echo "  [dry-run] would invoke: bin/run_scenario.sh $sid --from smoke-test --to smoke-test-judge"
  done
  if [[ "$SKIP_DETERMINISTIC" != "1" ]]; then
    echo "  [dry-run] would invoke: scripts/score_all_18.sh (deterministic confirmation)"
  fi
  exit 0
fi

# ---- Per-scenario sweep ----
SWEEP_START=$(date +%s)
COMPLETED=()
FAILED=()

for sid in "${SCENARIOS[@]}"; do
  echo ""
  echo "------------------------------------------"
  echo "  SCENARIO $sid — start: $(date)"
  echo "------------------------------------------"

  set +e
  bin/run_scenario.sh "$sid" --from smoke-test --to smoke-test-judge
  EXIT_CODE=$?
  set -e

  if [[ "$EXIT_CODE" -eq 0 ]]; then
    COMPLETED+=("$sid")
  else
    FAILED+=("$sid (exit $EXIT_CODE)")
    echo "  Continuing to next scenario despite failure."
  fi
done

SWEEP_END=$(date +%s)
TOTAL_SEC=$(( SWEEP_END - SWEEP_START ))
TOTAL_MIN=$(( TOTAL_SEC / 60 ))

echo ""
echo "=========================================="
echo "  LLM SWEEP COMPLETE"
echo "  Finished: $(date)"
echo "  Total time: ${TOTAL_MIN}m (${TOTAL_SEC}s)"
echo "=========================================="
echo "  smoke-test + smoke-test-judge completed (${#COMPLETED[@]}): ${COMPLETED[*]:-}"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "  smoke-test + smoke-test-judge FAILED    (${#FAILED[@]}): ${FAILED[*]}"
fi

# ---- Deterministic confirmation pass ----
if [[ "$SKIP_DETERMINISTIC" == "1" ]]; then
  echo ""
  echo "  Deterministic scorer skipped (per --skip-deterministic)."
  exit ${#FAILED[@]}
fi

echo ""
echo "=========================================="
echo "  Deterministic rubric scorer — ground-truth confirmation"
echo "  (no LLM, no network, byte-identical reproducibility)"
echo "=========================================="

# Run score_all_18.sh and capture its exit code
set +e
scripts/score_all_18.sh
SCORER_EXIT=$?
set -e

echo ""
if [[ "$SCORER_EXIT" -eq 0 ]]; then
  echo "  ✓ Deterministic scorer: ALL PASS"
else
  echo "  ✗ Deterministic scorer: ${SCORER_EXIT} failure(s)"
fi

# Combined exit: non-zero if EITHER the LLM sweep had failures OR the
# deterministic scorer didn't pass everything.
COMBINED_EXIT=$(( ${#FAILED[@]} + SCORER_EXIT ))
if [[ "$COMBINED_EXIT" -gt 0 ]]; then
  exit 1
fi
exit 0
