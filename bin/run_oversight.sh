#!/usr/bin/env bash
# ============================================================
# run_oversight.sh — Interactive end-to-end pipeline walkthrough.
#
# Runs all four phases (Pass 1, Pass 2, Validate, Smoke test) with a pause
# between each. After each phase, you can:
#   • inspect intermediates/NN/ files
#   • run quick sanity checks on a scenario folder
#   • abort if anything looks wrong
#
# Usage:
#   bin/run_oversight.sh            Interactive mode (recommended)
#   bin/run_oversight.sh --batch    Use Anthropic Batches API (50% cost, async)
#
# This script is the recommended path for the first full build. Once you've
# done one supervised run and trust the pipeline, switch to `make build-all`
# for the unattended path.
# ============================================================

set -euo pipefail

BATCH_FLAG=""
if [[ "${1:-}" == "--batch" ]]; then
  BATCH_FLAG="--batch"
  echo "[INFO] Running in BATCH mode (50% pricing, ~5-30 min per phase)"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

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
      echo "  diff <(head -20 intermediates/07/pass1.json) <(head -20 intermediates/07/pass2.json)"
      echo "      (only correlation-affected tiers should differ for Scenario 07)"
      ;;
    validate)
      echo "  ls -la scenarios/*/             # all 7 files present per scenario?"
      echo "  cat intermediates/*/qa_report.json | python -m json.tool | head -40"
      ;;
    smoke-test)
      echo "  cat intermediates/smoke_test_report.json | python -m json.tool"
      echo "  cat intermediates/smoke_test_summary.md"
      ;;
  esac
  echo ""
  read -r -p "Continue to next phase? [y/N]: " response
  case "$response" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted by user."; exit 0 ;;
  esac
}

echo "============================================================"
echo "  Cloud Governance Data-Gen — Supervised Pipeline Run"
echo "============================================================"
echo ""
echo "This script walks you through the four major phases:"
echo "  1. Pass 1 — Base telemetry generation (~\$101 / ~15 min)"
echo "  2. Pass 2 — Correlation injection    (~\$54  / ~8  min)"
echo "  3. Validate — QA + semantic checks   (~\$0   / ~1  min)"
echo "  4. Smoke test — Quality sanity check (~\$1.45 / ~6  min)"
echo ""
echo "                                  Total: ~\$157 / ~30 min interactive"
echo "                                         ~\$79  / ~65 min batch"
echo ""
read -r -p "Begin Phase 1 (Pass 1)? [y/N]: " response
case "$response" in
  [yY]|[yY][eE][sS]) ;;
  *) echo "Aborted by user."; exit 0 ;;
esac

# ============================================================
# Phase 1: Pass 1
# ============================================================
echo ""
echo ">>> Phase 1: Pass 1 (base telemetry generation)"
uv run python -m generator.cli pass1-all --yes $BATCH_FLAG
pause_for_review "pass1"

# ============================================================
# Phase 2: Pass 2
# ============================================================
echo ""
echo ">>> Phase 2: Pass 2 (cross-tier correlation injection)"
uv run python -m generator.cli pass2-all --yes $BATCH_FLAG
pause_for_review "pass2"

# ============================================================
# Phase 3: Validate
# ============================================================
echo ""
echo ">>> Phase 3: QA validator (contract + semantic checks)"
uv run python -m generator.cli validate-all --yes
pause_for_review "validate"

# ============================================================
# Phase 4: Smoke test
# ============================================================
echo ""
echo ">>> Phase 4: Smoke test (Opus baseline + Haiku judge)"
uv run python -m generator.cli smoke-test-all --yes $BATCH_FLAG
pause_for_review "smoke-test"

# ============================================================
# Done
# ============================================================
echo ""
echo "============================================================"
echo "  All four phases complete."
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Review the smoke test report (intermediates/smoke_test_summary.md)."
echo "  2. If the smoke test result is GREEN (≥14 of 18 passed) or YELLOW (12-13"
echo "     with documented exceptions), commit scenarios/ and hand off."
echo "  3. If RED, investigate the failing scenarios — likely a data-quality issue"
echo "     in Pass 1 or Pass 2."
echo ""
echo "To commit:"
echo "  git add scenarios/"
echo "  git commit -m 'Phase C complete: 18 scenarios generated and validated'"
echo ""
