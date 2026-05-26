#!/usr/bin/env bash
# ============================================================
# run_scenario.sh — Run the full data-gen + smoke-test pipeline for one scenario.
#
# Wraps the five phase-level CLI commands:
#   1. pass1            — Pass 1 telemetry generation (Sonnet, day-chunked)
#   2. pass2            — Pass 2 surgical refinement + correlation evidence
#   3. validate         — QA validator (contract + semantic checks)
#   4. smoke-test       — Opus recommendation against the scenario folder
#   5. smoke-test-judge — Haiku judge against the spec target
#
# Each phase's stdout/stderr is captured to its own log file under logs/,
# auto-versioned (vN) to match the existing manual naming convention.
# Subsequent phases short-circuit on failure with the failing phase's
# exit code preserved.
#
# Usage:
#   bin/run_scenario.sh NN                          Run all 5 phases for scenario NN.
#   bin/run_scenario.sh NN --from PHASE             Start from PHASE (skip earlier).
#   bin/run_scenario.sh NN --to PHASE               Stop after PHASE.
#   bin/run_scenario.sh NN --from pass2 --to validate
#   bin/run_scenario.sh NN --dry-run                Print commands without executing.
#   bin/run_scenario.sh -h | --help                 This message.
#
# PHASE ∈ {pass1, pass2, validate, smoke-test, smoke-test-judge}
#
# Wrap with nohup + caffeinate for unattended runs (macOS):
#   nohup caffeinate -i -d -s bin/run_scenario.sh 10 \
#         > logs/scenario_10_overall_v1.log 2>&1 &
#
# Resume after a partial-failure:
#   The error message will print the exact --from PHASE flag to use.
#   Checkpoints under intermediates/NN/ are preserved on failure, so
#   the resume run will skip work that the per-phase CLI commands can
#   detect as already done (pass2 verification, pass2 windows, etc.).
# ============================================================

set -euo pipefail

# ---- Locate repo + set PYTHONPATH ----
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# ---- Phase order (single source of truth) ----
# Plain indexed array — works on Bash 3.2 (macOS default) which lacks
# associative arrays (declare -A is Bash 4+ only).
PHASES=(pass1 pass2 validate smoke-test smoke-test-judge)

# Look up the 1-indexed phase number for a phase name.
# Used to build the log filename (logs/scenario_NN_phaseM_..._vN.log).
phase_num_of() {
  local target="$1" i
  for i in "${!PHASES[@]}"; do
    if [[ "${PHASES[$i]}" == "$target" ]]; then
      echo $((i + 1))
      return 0
    fi
  done
  return 1
}

# ---- Help ----
show_help() {
  sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'
}

# ---- Parse args ----
SCENARIO=""
FROM_PHASE="${PHASES[0]}"
TO_PHASE="${PHASES[${#PHASES[@]}-1]}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --from)
      [[ $# -ge 2 ]] || { echo "ERROR: --from requires an argument" >&2; exit 2; }
      FROM_PHASE="$2"; shift 2 ;;
    --to)
      [[ $# -ge 2 ]] || { echo "ERROR: --to requires an argument" >&2; exit 2; }
      TO_PHASE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -*) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
    *)
      if [[ -z "$SCENARIO" ]]; then
        SCENARIO="$1"; shift
      else
        echo "ERROR: unexpected positional argument: $1 (already have scenario=$SCENARIO)" >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -z "$SCENARIO" ]]; then
  echo "ERROR: scenario number is required (e.g. '10' or '01')" >&2
  echo "" >&2
  show_help >&2
  exit 2
fi

# Zero-pad single-digit scenarios ('1' → '01') for NN convention
if [[ "$SCENARIO" =~ ^[0-9]$ ]]; then
  SCENARIO="0$SCENARIO"
fi
if [[ ! "$SCENARIO" =~ ^[0-9]{2}$ ]]; then
  echo "ERROR: scenario must be a two-digit number (got '$SCENARIO')" >&2
  exit 2
fi

# ---- Validate phase names ----
phase_exists() {
  local p="$1"
  for q in "${PHASES[@]}"; do [[ "$q" == "$p" ]] && return 0; done
  return 1
}
phase_exists "$FROM_PHASE" || {
  echo "ERROR: --from invalid: '$FROM_PHASE' (allowed: ${PHASES[*]})" >&2; exit 2; }
phase_exists "$TO_PHASE" || {
  echo "ERROR: --to invalid: '$TO_PHASE' (allowed: ${PHASES[*]})" >&2; exit 2; }

# ---- Validate spec exists ----
SPEC_PATH="$REPO_ROOT/docs/internal/scenarios/${SCENARIO}.spec.yaml"
if [[ ! -f "$SPEC_PATH" ]]; then
  echo "ERROR: spec file not found: $SPEC_PATH" >&2
  echo "       (available: $(ls docs/internal/scenarios/ 2>/dev/null | grep -oE '^[0-9]{2}' | sort -u | tr '\n' ' '))" >&2
  exit 2
fi

# ---- Validate uv is on PATH (needed by every phase) ----
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' not found on PATH. Install uv or activate the project venv." >&2
  exit 127
fi

# ---- Build the phase list to actually run (intersection of FROM..TO) ----
RUN_PHASES=()
in_window=0
for p in "${PHASES[@]}"; do
  [[ "$p" == "$FROM_PHASE" ]] && in_window=1
  [[ "$in_window" == "1" ]] && RUN_PHASES+=("$p")
  [[ "$p" == "$TO_PHASE" ]] && break
done
if [[ "${#RUN_PHASES[@]}" -eq 0 ]]; then
  echo "ERROR: --from '$FROM_PHASE' comes after --to '$TO_PHASE' in phase order" >&2
  exit 2
fi

# ---- Helper: find next log version for a given phase ----
# Returns 1 + the highest existing vN, so version numbers grow
# chronologically rather than backfilling holes from earlier manual runs.
next_log_version() {
  local pnum="$1" pname_sanitized="$2"
  local prefix="logs/scenario_${SCENARIO}_phase${pnum}_${pname_sanitized}_v"
  local max=0
  shopt -s nullglob
  for f in "${prefix}"*.log; do
    # Extract the integer N from "..._vN.log"
    local n="${f##*_v}"
    n="${n%.log}"
    if [[ "$n" =~ ^[0-9]+$ ]] && (( n > max )); then
      max=$n
    fi
  done
  shopt -u nullglob
  echo "$((max + 1))"
}

# ---- Plan banner ----
echo "============================================================"
echo "  Scenario: $SCENARIO  ($(basename "$SPEC_PATH"))"
echo "  Phases:   ${RUN_PHASES[*]}"
[[ "$DRY_RUN" == "1" ]] && echo "  Mode:     dry-run (no commands will execute)"
echo "============================================================"

mkdir -p logs

# ---- Execute each phase in order ----
START_TIME=$(date +%s)
for PHASE in "${RUN_PHASES[@]}"; do
  PHASE_NUM_VAL=$(phase_num_of "$PHASE")
  # Filename uses underscores (matches existing v1 logs: 'smoke_test' not 'smoke-test')
  PHASE_FILE_NAME="${PHASE//-/_}"
  VERSION=$(next_log_version "$PHASE_NUM_VAL" "$PHASE_FILE_NAME")
  LOG_FILE="logs/scenario_${SCENARIO}_phase${PHASE_NUM_VAL}_${PHASE_FILE_NAME}_v${VERSION}.log"

  CMD=(uv run python -m generator.cli "$PHASE" "$SCENARIO")

  echo ""
  echo "  ── Phase $PHASE_NUM_VAL ($PHASE) ──"
  echo "     cmd: ${CMD[*]}"
  echo "     log: $LOG_FILE"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "     [dry-run] skipping execution"
    continue
  fi

  PHASE_START=$(date +%s)
  if "${CMD[@]}" > "$LOG_FILE" 2>&1; then
    PHASE_END=$(date +%s)
    DURATION=$((PHASE_END - PHASE_START))
    # Pretty-print duration
    if   [[ $DURATION -ge 60 ]]; then
      MIN=$((DURATION / 60))
      SEC=$((DURATION % 60))
      DUR_STR="${MIN}m${SEC}s"
    else
      DUR_STR="${DURATION}s"
    fi
    echo "     ✓ complete ($DUR_STR)"
  else
    EXIT_CODE=$?
    PHASE_END=$(date +%s)
    DURATION=$((PHASE_END - PHASE_START))
    echo "     ✗ FAILED after ${DURATION}s (exit code $EXIT_CODE)"
    echo ""
    echo "     ── Last 30 lines of $LOG_FILE ──"
    tail -30 "$LOG_FILE" | sed 's/^/       /'
    echo ""
    echo "     To resume from this phase after fixing the issue:"
    echo "       bin/run_scenario.sh $SCENARIO --from $PHASE"
    exit "$EXIT_CODE"
  fi
done

# ---- Final summary ----
TOTAL_END=$(date +%s)
TOTAL_DURATION=$((TOTAL_END - START_TIME))
if   [[ $TOTAL_DURATION -ge 60 ]]; then
  MIN=$((TOTAL_DURATION / 60))
  SEC=$((TOTAL_DURATION % 60))
  TOTAL_DUR_STR="${MIN}m${SEC}s"
else
  TOTAL_DUR_STR="${TOTAL_DURATION}s"
fi
echo ""
echo "============================================================"
echo "  ✓ Scenario $SCENARIO: all phases complete (${TOTAL_DUR_STR} total)"
echo "============================================================"
