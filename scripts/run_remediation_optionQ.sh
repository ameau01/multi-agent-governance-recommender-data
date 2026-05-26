#!/usr/bin/env bash
# ============================================================
# run_remediation_optionQ.sh — Phase 2 remediation, "quick" path.
#
# Runs targeted re-runs against the 11 failing scenarios, using
# the minimum work needed for each:
#
#   Cheap (validator now passes after Phase 1 edits — just smoke+judge):
#     09, 12, 17
#
#   Bypass validate gate (still fails on over-coupled data) — let
#   smoke-test see if Opus reaches the right diagnosis despite
#   coupling. Escalate to Option R only if it doesn't:
#     06, 14, 15, 16, 18
#
#   Re-run Pass 2 only (Pass 1 reused):
#     07 (spec fixed; planner re-runs)
#     11 (lag-zero check relaxed; windows reused, merger now succeeds)
#
#   Full re-run (Pass 1 chunker fix; cached day chunks reused so cheap):
#     05
#
# Per-scenario failures do NOT stop the sweep — the loop continues.
#
# Usage:
#   scripts/run_remediation_optionQ.sh            Run all remediations.
#   scripts/run_remediation_optionQ.sh --dry-run  Print plan, run nothing.
#   scripts/run_remediation_optionQ.sh -h|--help  This message.
#
# Wrap with nohup + caffeinate for unattended runs (macOS):
#   nohup caffeinate -i -d -s scripts/run_remediation_optionQ.sh \
#         > logs/remediation_optionQ_v1.log 2>&1 &
#
# Expected cost & time:
#   ~$8, ~45 min wall (single-threaded; scenario 05's Pass 1 aggregator
#   re-runs over cached chunks instantly).
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0

show_help() {
  sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Sanity: bin/run_scenario.sh must exist
if [[ ! -x bin/run_scenario.sh ]]; then
  echo "ERROR: bin/run_scenario.sh not found or not executable" >&2
  exit 2
fi

# ---- Build the remediation plan ----
# Parallel arrays (Bash 3.2 compatible — no declare -A).
# Each row = (scenario_id, --from PHASE, reason).
SCENARIOS=( 09             12             17             07             11             05             06             14             15             16             18           )
FROM_PHASES=( smoke-test    smoke-test     smoke-test     pass2          pass2          pass1          smoke-test     smoke-test     smoke-test     smoke-test     smoke-test  )
REASONS=(
  "validator now passes — smoke+judge only"
  "validator now passes — smoke+judge only"
  "validator now passes (coupling skip) — smoke+judge only"
  "spec fixed — re-run pass2; Pass 1 reused"
  "lag-zero relaxed — re-run pass2; windows reused"
  "aggregator now permissive — re-run Pass 1 over cached chunks"
  "validate still fails — bypass to smoke-test; over-coupled data"
  "validate still fails — bypass to smoke-test"
  "validate still fails — bypass to smoke-test"
  "validate still fails — bypass to smoke-test"
  "validate still fails — bypass to smoke-test"
)

# ---- Plan banner ----
echo "=========================================="
echo "  Remediation Option Q — plan"
echo "  Started: $(date)"
echo "=========================================="
echo ""
echo "  Re-run plan (11 scenarios):"
for i in "${!SCENARIOS[@]}"; do
  printf "    %s  --from %-12s  # %s\n" "${SCENARIOS[$i]}" "${FROM_PHASES[$i]}" "${REASONS[$i]}"
done
echo ""

if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] no commands will execute."
  exit 0
fi

# ---- Execute each step in order ----
COMPLETED=()
FAILED=()
SWEEP_START=$(date +%s)

for i in "${!SCENARIOS[@]}"; do
  sid="${SCENARIOS[$i]}"
  from_phase="${FROM_PHASES[$i]}"

  echo ""
  echo "------------------------------------------"
  echo "  SCENARIO $sid — start: $(date)"
  echo "    plan: --from $from_phase to smoke-test-judge"
  echo "    why : ${REASONS[$i]}"
  echo "------------------------------------------"

  set +e
  bin/run_scenario.sh "$sid" --from "$from_phase" --to smoke-test-judge
  EXIT_CODE=$?
  set -e

  if [[ "$EXIT_CODE" -eq 0 ]]; then
    COMPLETED+=("$sid")
    echo "  PASS: $sid complete"
  else
    FAILED+=("$sid (exit $EXIT_CODE)")
    echo "  FAIL: $sid (exit $EXIT_CODE) — continuing to next"
  fi
done

# ---- Summary ----
SWEEP_END=$(date +%s)
TOTAL_SEC=$(( SWEEP_END - SWEEP_START ))
TOTAL_MIN=$(( TOTAL_SEC / 60 ))

echo ""
echo "=========================================="
echo "  Remediation Option Q complete"
echo "  Finished: $(date)"
echo "  Total time: ${TOTAL_MIN}m (${TOTAL_SEC}s)"
echo "=========================================="
echo "  Completed (${#COMPLETED[@]}): ${COMPLETED[*]:-}"
echo "  Failed    (${#FAILED[@]}): ${FAILED[*]:-}"
echo ""
echo "Next steps:"
echo "  - For each successfully completed scenario, inspect:"
echo "      cat intermediates/NN/smoke_test_judge.json | python3 -m json.tool"
echo "  - Aggregate pass/partial/fail across all 18:"
echo "      for sid in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18; do"
echo "        j=intermediates/\$sid/smoke_test_judge.json"
echo "        if [ -f \"\$j\" ]; then"
echo "          outcome=\$(python3 -c \"import json; print(json.loads(open('\$j').read())['outcome'])\")"
echo "          echo \"  \$sid: \$outcome\""
echo "        fi"
echo "      done"
echo ""
echo "  - For any scenario where Opus's recommendation looks wrong, escalate"
echo "    to Option R (regenerate Pass 1 with the phase-decoupling prompt):"
echo "      bin/run_scenario.sh NN     # full pipeline from scratch"

# Non-zero exit if anything failed so caller can detect overall status
if [[ "${#FAILED[@]}" -gt 0 ]]; then
  exit 1
fi
