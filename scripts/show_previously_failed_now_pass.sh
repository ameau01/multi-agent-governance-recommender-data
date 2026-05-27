#!/usr/bin/env bash
# ============================================================
# show_previously_failed_now_pass.sh — Verification script.
#
# Goal: prove that scenarios which previously failed (or partial'd) under
# the Haiku LLM judge now PASS under the deterministic rubric scorer, with
# full per-check detail so you can audit WHY each one passes.
#
# How it works:
#   1. Scans intermediates/NN/smoke_test_judge.json for every scenario
#      that has judge outcome != "pass" (partial or fail).
#   2. For each such scenario, runs the deterministic scorer.
#   3. Prints a side-by-side: old LLM-judge verdict vs new scorer verdict,
#      and the full check-by-check breakdown for the new scorer.
#
# If all previously-failed scenarios now pass, you should see ALL ✓
# in the new-scorer output, with each rubric check explained.
#
# Usage:
#   scripts/show_previously_failed_now_pass.sh
#       Run the verification (no LLM cost, ~2 seconds).
#   scripts/show_previously_failed_now_pass.sh --include-all
#       Include all 18 scenarios in the output, not just the previously-failed.
#   scripts/show_previously_failed_now_pass.sh -h | --help
#       This message.
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

INCLUDE_ALL=0

show_help() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --include-all) INCLUDE_ALL=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Run a single Python session that does everything (faster than per-scenario)
INCLUDE_ALL="$INCLUDE_ALL" python3 <<'PY'
import json, os
from pathlib import Path
from qa.deterministic_scorer import score_all, score_recommendation

INCLUDE_ALL = os.environ.get("INCLUDE_ALL", "0") == "1"

# Determine which scenarios are "previously failed/partial" via existing judge outputs
previously_failed = []
previously_passed = []
for sid in [f"{i:02d}" for i in range(1, 19)]:
    judge_path = Path(f'intermediates/{sid}/smoke_test_judge.json')
    if not judge_path.exists():
        previously_failed.append((sid, "(no judge result)"))
        continue
    d = json.loads(judge_path.read_text())
    out = d.get("outcome", "?")
    if out == "pass":
        previously_passed.append((sid, out))
    else:
        previously_failed.append((sid, out))

target = (previously_failed + previously_passed) if INCLUDE_ALL else previously_failed

print("=" * 92)
print(f"  TRANSITION REPORT — {len(previously_failed)} scenario(s) previously failed/partial")
print(f"                      under LLM judge. Now showing deterministic scorer result.")
if INCLUDE_ALL:
    print(f"                      (--include-all: also showing {len(previously_passed)} previously-passing.)")
print("=" * 92)

# Header summary
print()
print(f"  {'sid':>4s}  {'old LLM judge':>16s}  {'new deterministic':>18s}  rationale (first line of rubric)")
print("  " + "-" * 90)
flipped = 0
regressed = 0
for sid, old in target:
    smoke_path = Path(f'intermediates/{sid}/smoke_test.json')
    if not smoke_path.exists():
        print(f"  {sid}    {old:>16s}  {'(no smoke_test)':>18s}  --")
        continue
    rec = json.loads(smoke_path.read_text())
    meta_path = Path(f'scenarios/{sid}/metadata.json')
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    new = score_recommendation(sid, rec, meta)
    new_label = "PASS" if new.overall_passed else "FAIL"
    rationale = (new.rubric_rationale or "")[:60]
    transition = ""
    if old != "pass" and new.overall_passed:
        flipped += 1
        transition = "  ← flipped to pass"
    if old == "pass" and not new.overall_passed:
        regressed += 1
        transition = "  ← REGRESSION!"
    print(f"  {sid}    {old:>16s}  {new_label:>18s}  {rationale}{transition}")

print()
print(f"  Flipped failures → pass: {flipped}")
if regressed:
    print(f"  REGRESSIONS (was pass, now fail): {regressed}")

# Detailed check breakdown for previously-failed scenarios
print()
print("=" * 92)
print("  PER-CHECK DETAIL for previously-failed scenarios")
print("=" * 92)
for sid, old_outcome in previously_failed:
    smoke_path = Path(f'intermediates/{sid}/smoke_test.json')
    if not smoke_path.exists():
        continue
    rec = json.loads(smoke_path.read_text())
    meta_path = Path(f'scenarios/{sid}/metadata.json')
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    new = score_recommendation(sid, rec, meta)

    print()
    print(f"  ----- SCENARIO {sid} -----")
    print(f"    Previous LLM judge:      {old_outcome}")
    print(f"    Deterministic scorer:    {'PASS' if new.overall_passed else 'FAIL'}")
    print(f"    Rubric rationale: {new.rubric_rationale}")
    print(f"    Check-by-check:")
    for c in new.checks:
        flag = '✓' if c.passed else '✗'
        msg = c.message
        if len(msg) > 95: msg = msg[:93] + ".."
        print(f"      {flag} {c.name:25s}  {msg}")
        # Extra context for the most interesting check types
        if c.name == "action_keywords" and c.detail:
            d = c.detail
            n_groups = len(d.get("groups", []))
            matched = d.get("matched_group_indices", [])
            print(f"          └─ matched group(s) {matched} of {n_groups} possible "
                  f"(needed min={d.get('min_match', n_groups)})")
        elif c.name == "multi_tier_evidence" and c.detail:
            d = c.detail
            print(f"          └─ tiers mentioned: {d.get('mentioned_tiers', [])} of "
                  f"required {d.get('required_tiers', [])}")
        elif c.name == "fixture_citation" and c.detail:
            d = c.detail
            cited = d.get("cited", [])
            ids = d.get("identifiers", [])
            if ids:
                print(f"          └─ cited {len(cited)} of {len(ids)} fixture identifiers")

print()
print("=" * 92)
PY
