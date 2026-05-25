#!/usr/bin/env bash
# ============================================================
# 05_smoke_test_judge.sh — Phase 5: Smoke-test judge (Haiku)
#
# For each scenario, reads the Opus recommendation saved in Phase 04 and
# compares it against the scenario spec's target_recommendation on four
# fields:
#   - finding_type:    exact string match
#   - primary_tier:    exact string match (None matches None)
#   - action_category: exact enum match (None matches None)
#   - specific_change: Haiku LLM-as-judge ("substantively the same? YES/NO")
#
# Scoring: pass (4/4) | partial (2-3/4) | fail (0-1/4).
# Aggregate threshold: ≥14 pass = GREEN, 12-13 = YELLOW, ≤11 = RED.
#
# Model:        Claude Haiku 4.5
# Scenarios:    18 (all)
# Cost:         ~$0.01 total (Haiku is cheap; judging is cheap)
# Wall time:    ~1 min interactive
#
# RESUMABLE: each scenario's smoke_test_judge.json is checkpointed.
# Re-running skips scenarios already judged.
#
# REQUIRES: Phase 04 (smoke test) must have completed first — judge reads
# `intermediates/NN/smoke_test.json` as input.
#
# Usage:
#   bin/05_smoke_test_judge.sh           Interactive, with confirmation prompt
#   bin/05_smoke_test_judge.sh --batch   Anthropic Batches API (50% cost, async)
#   bin/05_smoke_test_judge.sh --yes     Skip the confirmation prompt
#   bin/05_smoke_test_judge.sh --force   Re-judge every scenario
# ============================================================

set -euo pipefail

BATCH_FLAG=""; YES_FLAG=""; FORCE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --batch) BATCH_FLAG="--batch" ;;
    --yes)   YES_FLAG="--yes" ;;
    --force) FORCE_FLAG="--force" ;;
    -h|--help) sed -n '2,33p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "============================================================"
echo "  Phase 05 — Smoke-test judge (Haiku 4.5)"
echo "============================================================"

uv run python -m generator.cli smoke-test-judge-all $BATCH_FLAG $YES_FLAG $FORCE_FLAG
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "------------------------------------------------------------"
  echo "Phase 05 complete. Review hints:"
  echo "  cat intermediates/smoke_test_report.json | jq ."
  echo "  cat intermediates/smoke_test_summary.md"
  echo ""
  echo "Interpretation:"
  echo "  GREEN  (≥14 of 18 pass) → proceed with handoff"
  echo "  YELLOW (12-13 pass)     → spot-check the failures, then proceed"
  echo "  RED    (≤11 pass)       → investigate data quality"
  echo ""
  echo "Hard scenarios (06, 14, 15, 16, 17, 18) are EXPECTED to fail or"
  echo "partial — they're the restraint / SLA-review / diagnostic-deferral"
  echo "cases that the multi-agent system is designed to handle but a"
  echo "single-call LLM cannot. Easy scenarios passing + hard ones failing"
  echo "is exactly the signal we want."
  echo ""
  echo "If GREEN or acceptable YELLOW, commit the scenarios:"
  echo "  git add scenarios/"
  echo "  git commit -m 'Phase C complete: 18 scenarios generated and validated'"
fi

exit $EXIT_CODE
