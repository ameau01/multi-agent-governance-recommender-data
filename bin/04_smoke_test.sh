#!/usr/bin/env bash
# ============================================================
# 04_smoke_test.sh — Phase 4: Smoke-test recommendation (Opus)
#
# For each scenario, bundles the scenario folder (metadata minus target,
# telemetry summaries, correlation_evidence, main.tf) into a single prompt
# and asks Opus 4.6 for a TargetRecommendation-shaped output.
#
# DOES NOT JUDGE THE OUTPUT — that's Phase 05. This phase saves Opus's raw
# recommendation to `intermediates/NN/smoke_test.json` so you can:
#   - inspect the raw recommendations before judging
#   - abort here without wasting judge tokens if a recommendation looks wrong
#   - re-run the judge later against unchanged recommendations
#
# Model:        Claude Opus 4.6
# Scenarios:    18 (all)
# Cost:         ~$1.44 interactive, ~$0.72 batch
# Wall time:    ~5 min interactive, ~12 min batch
#
# RESUMABLE: each scenario's smoke_test.json is checkpointed atomically.
# Re-running skips scenarios that already have a saved recommendation.
#
# REQUIRES: scenarios/NN/ folders must be present (Phases 01-03 complete).
#
# Usage:
#   bin/04_smoke_test.sh             Interactive, with confirmation prompt
#   bin/04_smoke_test.sh --batch     Anthropic Batches API (50% cost, async)
#   bin/04_smoke_test.sh --yes       Skip the confirmation prompt
#   bin/04_smoke_test.sh --force     Ignore existing checkpoints; re-run all
# ============================================================

set -euo pipefail

BATCH_FLAG=""; YES_FLAG=""; FORCE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --batch) BATCH_FLAG="--batch" ;;
    --yes)   YES_FLAG="--yes" ;;
    --force) FORCE_FLAG="--force" ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)"; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================================"
echo "  Phase 04 — Smoke-test recommendation (Opus 4.6)"
echo "============================================================"
echo "  Opus recommendations will be checkpointed to disk BEFORE"
echo "  the judge runs. Safe to abort here and review outputs"
echo "  before continuing to Phase 05."
echo ""

uv run python -m generator.cli smoke-test-all $BATCH_FLAG $YES_FLAG $FORCE_FLAG
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "------------------------------------------------------------"
  echo "Phase 04 complete. Review hints:"
  echo "  ls -la intermediates/*/smoke_test.json"
  echo "  cat intermediates/07/smoke_test.json | jq ."
  echo "  # Pay particular attention to scenarios 06, 14, 15, 16, 17, 18"
  echo "  # (restraint / SLA-review / diagnostic-deferral cases — these are"
  echo "  # deliberately hard for a single-call LLM and may fail the judge"
  echo "  # later; that's expected and OK)."
  echo ""
  echo "If a recommendation looks wrong (model misunderstood the scenario,"
  echo "evidence was insufficient, etc.), you can fix the scenario spec,"
  echo "regenerate Pass 1/Pass 2 for that scenario, and re-run this phase"
  echo "for just that one scenario:"
  echo "  make smoke-test SCENARIO=NN"
  echo ""
  echo "Next step:  bin/05_smoke_test_judge.sh"
fi

exit $EXIT_CODE
