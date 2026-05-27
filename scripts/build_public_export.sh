#!/usr/bin/env bash
# ============================================================
# build_public_export.sh — Build the public-export/ folder from
# the private repo's intermediates and scenarios.
#
# Stages:
#   1. Sanitize + copy scenarios into dataset/scenarios/NN/
#   2. Emit expectations JSON from src/qa/rubrics.py
#   3. Generate sample_predictions.json from real smoke_test outputs
#   4. Run banned-word grep; fail the build if any forbidden string hits
#
# Usage:
#   scripts/build_public_export.sh
#   scripts/build_public_export.sh --skip-grep   # debug only
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

SKIP_GREP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-grep) SKIP_GREP=1; shift ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown flag: $1" >&2; exit 2 ;;
  esac
done

OUT="public-export"
[[ -d "$OUT" ]] || { echo "ERROR: $OUT/ does not exist; create folder skeleton first" >&2; exit 2; }

echo "============================================================"
echo "  Building $OUT/ from private artifacts"
echo "============================================================"

# ---- 1. Sanitize + copy scenarios ----
echo ""
echo "[1/4] Sanitize + copy scenarios..."
python3 scripts/_build_export_helpers.py copy-scenarios

# ---- 2. Generate expectations JSON ----
echo ""
echo "[2/4] Generate expectations JSON from rubrics..."
python3 scripts/_build_export_helpers.py emit-expectations

# ---- 3. Generate sample_predictions.json ----
echo ""
echo "[3/4] Generate sample_predictions.json (degraded from real outputs)..."
python3 scripts/_build_export_helpers.py emit-sample-predictions

# ---- 4. Banned-word grep ----
echo ""
echo "[4/4] Sanitization grep..."
if [[ "$SKIP_GREP" == "1" ]]; then
  echo "  SKIPPED (--skip-grep)"
else
  scripts/_build_export_grep.sh "$OUT"
fi

echo ""
echo "============================================================"
echo "  public-export build complete"
echo "============================================================"
