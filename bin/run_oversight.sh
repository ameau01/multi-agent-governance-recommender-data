#!/usr/bin/env bash
# ============================================================
# run_oversight.sh — Interactive end-to-end pipeline walkthrough.
#
# Walks the five major phases with a pause between each. After each phase
# you can inspect intermediates, run sanity checks, or abort cleanly.
#
# All phases are RESUMABLE. If your Mac sleeps, your shell exits, or the
# pipeline crashes mid-run, just re-execute this script (or the specific
# phase). Completed scenarios are detected via valid checkpoint files in
# intermediates/NN/ and skipped — you only pay for the scenarios that
# weren't already done.
#
# Phases (in order):
#   1. pass1               Base telemetry generation (Sonnet 4.6)        ~$101 / ~15 min
#   2. pass2               Cross-tier correlation injection (Sonnet 4.6) ~$54  / ~8  min
#   3. validate            QA + semantic checks (no LLM)                 ~$0   / ~1  min
#   4. smoke-test          Opus recommendation per scenario              ~$1.44 / ~5 min
#   5. smoke-test-judge    Haiku judge of saved recommendations          ~$0.01 / ~1 min
#                                                                  Total: ~$157 / ~30 min
#                                                  With --batch:  ~$79  / ~65 min
#
# Usage:
#   bin/run_oversight.sh                 Interactive mode (recommended)
#   bin/run_oversight.sh --batch         Use Anthropic Batches API (50% cost, async)
#   bin/run_oversight.sh --resume        Continue from where a previous run stopped
#                                        (this is the default behavior anyway —
#                                        --resume just makes intent explicit)
#
# Recovery example:
#   Mac sleeps during Pass 1 after 12 of 18 scenarios.
#   You wake up. Re-run:  bin/run_oversight.sh
#   Phase 1 prints: "Already complete: 12, Remaining: 6"
#   Cost preview: only the 6 remaining scenarios.
# ============================================================

set -euo pipefail

BATCH_FLAG=""
EXPLICIT_RESUME="false"
for arg in "$@"; do
  case "$arg" in
    --batch)
      BATCH_FLAG="--batch"
      ;;
    --resume)
      EXPLICIT_RESUME="true"   # informational; behavior is unchanged
      ;;
    -h|--help)
      sed -n '2,40p' "$0" | sed 's/^# //; s/^#//'
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg"
      echo "Run with --help for usage."
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "$BATCH_FLAG" ]]; then
  echo "[INFO] Running in BATCH mode (50% pricing, ~5-30 min per phase)"
fi

pause_for_review() {
  local phase="$1"
  echo ""
  echo "------------------------------------------------------------"
  echo "Phase '$phase' complete."
  echo ""
  echo "What to review now:"
  case "$phase" in
    pass1)
      echo "  ls -la intermediates/*/pass1.json"
      echo "  head -50 intermediates/01/pass1.json    # spot-check Scenario 01"
      echo "  head -50 intermediates/07/pass1.json    # spot-check Scenario 07"
      ;;
    pass2)
      echo "  ls -la intermediates/*/pass2.json"
      echo "  ls -la scenarios/*/correlation_evidence.json"
      echo "  # Only correlation-affected tiers should differ:"
      echo "  diff <(jq .Compute_Metrics[0:3] intermediates/07/pass1.json) \\"
      echo "       <(jq .Compute_Metrics[0:3] intermediates/07/pass2.json)"
      ;;
    validate)
      echo "  ls -la scenarios/*/                # all 7 files present per scenario?"
      echo "  cat intermediates/*/qa_report.json | python -m json.tool | head -40"
      ;;
    smoke-test)
      echo "  # Opus recommendations are saved; judge has NOT run yet."
      echo "  ls -la intermediates/*/smoke_test.json"
      echo "  cat intermediates/07/smoke_test.json | python -m json.tool"
      echo "  # If a recommendation looks wrong, you can abort here and fix the"
      echo "  # scenario spec without spending judge tokens on bad data."
      ;;
    smoke-test-judge)
      echo "  cat intermediates/smoke_test_report.json | python -m json.tool"
      echo "  cat intermediates/smoke_test_summary.md"
      ;;
  esac
  echo ""
  read -r -p "Continue to next phase? [y/N]: " response
  case "$response" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted by user. State is preserved — re-run this script to continue."; exit 0 ;;
  esac
}

echo "============================================================"
echo "  Cloud Governance Data-Gen — Supervised Pipeline Run"
echo "============================================================"
echo ""
echo "This script walks you through the five major phases:"
echo ""
echo "  1. Pass 1              Base telemetry (Sonnet 4.6)             ~\$101 / ~15 min"
echo "  2. Pass 2              Correlation injection (Sonnet 4.6)      ~\$54  / ~8 min"
echo "  3. Validate            QA + semantic checks (no LLM)           ~\$0   / ~1 min"
echo "  4. Smoke test          Opus recommendation per scenario        ~\$1.44 / ~5 min"
echo "  5. Smoke test judge    Haiku judge of saved recommendations    ~\$0.01 / ~1 min"
echo "                                                            Total: ~\$157 / ~30 min"
echo "                                            With --batch:    ~\$79  / ~65 min"
echo ""
echo "All phases are RESUMABLE. Mac sleep, Ctrl-C, network blips, OOM — none"
echo "of these will cause double-billing. Already-completed scenarios are"
echo "detected via checkpoint files and skipped on the next run."
echo ""
if [[ "$EXPLICIT_RESUME" == "true" ]]; then
  echo "[--resume specified — same behavior as the default; phase commands"
  echo " always detect and skip completed scenarios.]"
  echo ""
fi
read -r -p "Begin Phase 1 (Pass 1)? [y/N]: " response
case "$response" in
  [yY]|[yY][eE][sS]) ;;
  *) echo "Aborted by user."; exit 0 ;;
esac

# ============================================================
# Phase 1: Pass 1 (Sonnet)
# ============================================================
echo ""
echo ">>> Phase 1: Pass 1 (base telemetry generation, Sonnet 4.6)"
uv run python -m generator.cli pass1-all --yes $BATCH_FLAG
pause_for_review "pass1"

# ============================================================
# Phase 2: Pass 2 (Sonnet, correlation scenarios only)
# ============================================================
echo ""
echo ">>> Phase 2: Pass 2 (cross-tier correlation injection, Sonnet 4.6)"
uv run python -m generator.cli pass2-all --yes $BATCH_FLAG
pause_for_review "pass2"

# ============================================================
# Phase 3: Validate (deterministic, no LLM)
# ============================================================
echo ""
echo ">>> Phase 3: QA validator (contract + semantic checks, no LLM)"
uv run python -m generator.cli validate-all --yes
pause_for_review "validate"

# ============================================================
# Phase 4: Smoke test (Opus recommendation per scenario)
# Opus output is saved BEFORE the judge runs, so an interrupted Phase 5
# does not waste Opus budget.
# ============================================================
echo ""
echo ">>> Phase 4: Smoke test recommendation (Opus 4.6)"
echo "    Each scenario's Opus output is checkpointed to intermediates/NN/smoke_test.json"
echo "    before Phase 5 starts. Safe to abort here and continue later."
uv run python -m generator.cli smoke-test-all --yes $BATCH_FLAG
pause_for_review "smoke-test"

# ============================================================
# Phase 5: Smoke test judge (Haiku, scores saved recommendations)
# ============================================================
echo ""
echo ">>> Phase 5: Smoke test judge (Haiku 4.5)"
echo "    Reads each scenario's Opus output from intermediates/NN/smoke_test.json"
echo "    and produces a 4-field judgment. Cheap (~\$0.01 total)."
uv run python -m generator.cli smoke-test-judge-all --yes $BATCH_FLAG
pause_for_review "smoke-test-judge"

# ============================================================
# Done
# ============================================================
echo ""
echo "============================================================"
echo "  All five phases complete."
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Review the smoke test report:"
echo "       cat intermediates/smoke_test_summary.md"
echo "  2. If GREEN (≥14 of 18 passed) or YELLOW (12-13 with documented"
echo "     exceptions for the hard scenarios), commit scenarios/ and hand off."
echo "  3. If RED, investigate the failing scenarios — likely a data-quality"
echo "     issue in Pass 1 or Pass 2 for those specific scenarios. You can"
echo "     re-run Pass 1 for just one scenario:"
echo "       make pass1 SCENARIO=NN"
echo "     and then resume from Phase 2:"
echo "       bin/run_oversight.sh"
echo ""
echo "To commit:"
echo "  git add scenarios/"
echo "  git commit -m 'Phase C complete: 18 scenarios generated and validated'"
echo ""
