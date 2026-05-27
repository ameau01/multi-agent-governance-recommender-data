#!/usr/bin/env bash
# ============================================================
# test_dataset_clone.sh — Simulate cloning just the dataset/ subfolder
# and running its bundled eval.py.
#
# What this does:
#   1. Creates a fresh temp folder under $TMPDIR (default /tmp).
#   2. Copies public-export/dataset/ into the temp folder.
#      This simulates `git clone --filter` of only the dataset subtree.
#   3. Runs dataset/eval.py against three predictions files:
#        A. sample_predictions.json (the bundled sample — should PASS Floor)
#        B. gold_predictions.json   (assembled from handcrafted answers)
#        C. broken_predictions.json (deliberately malformed — should FAIL)
#   4. Prints a clear summary of what each test proved.
#
# What this does NOT test:
#   - eval-set/ scoring. That requires cloning eval-set/ too. A separate
#     script for that workflow comes next.
#
# Usage:
#   scripts/test_dataset_clone.sh
#   scripts/test_dataset_clone.sh --keep-tmp   # leave the temp folder behind
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/public-export/dataset"

KEEP_TMP=0
[[ "${1:-}" == "--keep-tmp" ]] && KEEP_TMP=1

if [[ ! -d "$SRC" ]]; then
  echo "ERROR: $SRC does not exist. Run scripts/build_public_export.sh first." >&2
  exit 2
fi

TEMP_BASE="${TMPDIR:-/tmp}"
# Strip trailing slash (macOS TMPDIR ends with /)
TEMP_BASE="${TEMP_BASE%/}"
TEMP="$TEMP_BASE/test_dataset_clone_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$TEMP"

if [[ "$KEEP_TMP" != "1" ]]; then
  trap 'echo ""; echo "  Cleaning up $TEMP"; rm -rf "$TEMP"' EXIT
fi

echo "============================================================"
echo "  Dataset clone test"
echo "  Source: $SRC"
echo "  Temp:   $TEMP"
echo "============================================================"

# ---- Step 1: simulate clone ----
echo ""
echo "[1/4] Copying dataset/ into temp folder..."
cp -R "$SRC" "$TEMP/dataset"
echo "       Files copied: $(find "$TEMP/dataset" -type f | wc -l | tr -d ' ')"
echo "       Size:         $(du -sh "$TEMP/dataset" | cut -f1)"

cd "$TEMP/dataset"

# ---- Step 2: assemble a gold predictions file from the handcrafted answers ----
echo ""
echo "[2/4] Assembling gold_predictions.json from handcrafted answers..."
python3 <<'PY'
import json
from pathlib import Path
preds = []
for sid in [f"{i:02d}" for i in range(1, 19)]:
    p = Path(f"scenarios/{sid}/handcrafted_recommendation.json")
    preds.append(json.loads(p.read_text()))
Path("gold_predictions.json").write_text(json.dumps({"predictions": preds}, indent=2))
print(f"  wrote gold_predictions.json with {len(preds)} predictions")
PY

# ---- Step 3: write a deliberately broken predictions file ----
echo ""
echo "[3/4] Writing broken_predictions.json (deliberately malformed)..."
python3 <<'PY'
import json
broken = {
  "predictions": [
    # Missing required fields
    {"scenario_id": "01"},
    # Wrong finding_type
    {"scenario_id": "02", "finding_type": "not_a_real_type",
     "specific_change": "x", "primary_tier": "compute",
     "action_category": "rightsizing"},
    # specific_change too short
    {"scenario_id": "03", "finding_type": "issue_found",
     "specific_change": "fix it", "primary_tier": "database",
     "action_category": "rightsizing"},
    # Unknown action_category
    {"scenario_id": "04", "finding_type": "issue_found",
     "specific_change": "Replace the index with something useful and tune the pool.",
     "primary_tier": "database", "action_category": "magical_fix"},
  ]
}
from pathlib import Path
Path("broken_predictions.json").write_text(json.dumps(broken, indent=2))
print("  wrote broken_predictions.json with 4 deliberately bad entries")
PY

# ---- Step 4: run eval.py three times ----
echo ""
echo "[4/4] Running dataset/eval.py against three files..."

echo ""
echo "------------------------------------------------------------"
echo "  Test A: sample_predictions.json (bundled sample)"
echo "  Expected: PASS (2 predictions, both shape-valid)"
echo "------------------------------------------------------------"
set +e
python3 eval.py --predictions sample_predictions.json
EC_A=$?
set -e
echo "  Exit code: $EC_A (expected 0)"

echo ""
echo "------------------------------------------------------------"
echo "  Test B: gold_predictions.json (the handcrafted answers)"
echo "  Expected: PASS (18 predictions, all shape-valid)"
echo "------------------------------------------------------------"
set +e
python3 eval.py --predictions gold_predictions.json
EC_B=$?
set -e
echo "  Exit code: $EC_B (expected 0)"

echo ""
echo "------------------------------------------------------------"
echo "  Test C: broken_predictions.json (deliberately malformed)"
echo "  Expected: FAIL (4 predictions, every one has problems)"
echo "------------------------------------------------------------"
set +e
python3 eval.py --predictions broken_predictions.json
EC_C=$?
set -e
echo "  Exit code: $EC_C (expected 1)"

# ---- Summary ----
echo ""
echo "============================================================"
echo "  Summary"
echo "============================================================"
printf "  Test A (sample)  exit %d  %s\n" "$EC_A" "$([[ $EC_A -eq 0 ]] && echo 'OK' || echo 'UNEXPECTED')"
printf "  Test B (gold)    exit %d  %s\n" "$EC_B" "$([[ $EC_B -eq 0 ]] && echo 'OK' || echo 'UNEXPECTED')"
printf "  Test C (broken)  exit %d  %s\n" "$EC_C" "$([[ $EC_C -eq 1 ]] && echo 'OK (failure caught correctly)' || echo 'UNEXPECTED')"
echo ""
if [[ "$KEEP_TMP" == "1" ]]; then
  echo "  Temp folder kept at: $TEMP"
fi

# Overall: A and B must be 0; C must be 1
if [[ $EC_A -eq 0 && $EC_B -eq 0 && $EC_C -eq 1 ]]; then
  echo "  All three tests behaved as expected."
  exit 0
else
  echo "  At least one test behaved unexpectedly. Inspect output above."
  exit 1
fi
