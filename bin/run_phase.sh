#!/usr/bin/env bash
# ============================================================
# run_phase.sh — DEPRECATED. Use the numbered per-phase scripts instead.
#
# This script has been superseded by per-phase numbered scripts that give
# better per-phase oversight + review hints:
#
#     bin/01_pass1.sh
#     bin/02_pass2.sh
#     bin/03_validate.sh
#     bin/04_smoke_test.sh
#     bin/05_smoke_test_judge.sh
#
# Run them in order. Each is RESUMABLE — re-running picks up where a
# previous interrupted run stopped, and you only pay for the remaining
# scenarios.
#
# This file is kept temporarily to avoid breaking any external references
# but will be removed. You can safely:
#     rm bin/run_phase.sh
# ============================================================

echo "DEPRECATED: bin/run_phase.sh has been superseded."
echo ""
echo "Use the numbered per-phase scripts instead:"
echo "  bin/01_pass1.sh             # Pass 1, base telemetry"
echo "  bin/02_pass2.sh             # Pass 2, correlation injection"
echo "  bin/03_validate.sh          # QA validation"
echo "  bin/04_smoke_test.sh        # Opus recommendation"
echo "  bin/05_smoke_test_judge.sh  # Haiku judge"
echo ""
echo "All five accept --batch, --yes, --force flags. All are resumable."
echo "Safe to delete this file:  rm bin/run_phase.sh"
exit 1
