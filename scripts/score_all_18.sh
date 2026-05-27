#!/usr/bin/env bash
# ============================================================
# score_all_18.sh — Run the deterministic rubric scorer against
# every scenario's smoke_test.json and print a complete scorecard.
#
# This is the "one more time, all 18, confirm everything passes"
# verification. No LLM call, no network — pure Python rubric checks.
# Same input → identical output, always.
#
# Reads:
#   intermediates/NN/smoke_test.json   (the agent's recommendation)
#   scenarios/NN/metadata.json         (for fixture-citation checks)
# Rubrics come from:
#   src/qa/rubrics.py                  (18 per-scenario rubrics)
#
# Usage:
#   scripts/score_all_18.sh
#       Compact scorecard (pass/fail per scenario; failure summaries inline).
#   scripts/score_all_18.sh --verbose
#       Full check-by-check breakdown for every scenario.
#   scripts/score_all_18.sh --json
#       Emit structured JSON to stdout (machine-readable).
#   scripts/score_all_18.sh --output FILE
#       Save output to FILE (tee — prints to terminal AND writes to file).
#       Works with --verbose and --json. Parent dirs auto-created.
#   scripts/score_all_18.sh -h | --help
#       This message.
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

VERBOSE=0
EMIT_JSON=0
OUTPUT_FILE=""

show_help() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --verbose) VERBOSE=1; shift ;;
    --json)    EMIT_JSON=1; shift ;;
    --output)
      [[ $# -ge 2 ]] || { echo "ERROR: --output requires a path" >&2; exit 2; }
      OUTPUT_FILE="$2"; shift 2 ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# Ensure --output's parent dir exists
if [[ -n "$OUTPUT_FILE" ]]; then
  mkdir -p "$(dirname "$OUTPUT_FILE")"
fi

# Write the python scorer logic to a temp file so we can conditionally pipe
# its output through tee without juggling two heredocs. The temp file is
# cleaned up on exit.
PYSCRIPT=$(mktemp -t score_all_XXXXXX.py)
trap 'rm -f "$PYSCRIPT"' EXIT

cat > "$PYSCRIPT" <<'PY'
import json, os
from pathlib import Path
from qa.deterministic_scorer import score_all

VERBOSE = os.environ.get("VERBOSE", "0") == "1"
EMIT_JSON = os.environ.get("EMIT_JSON", "0") == "1"

results = score_all(Path("intermediates"), Path("scenarios"))

if EMIT_JSON:
    out = {sid: r.to_dict() for sid, r in sorted(results.items())}
    print(json.dumps(out, indent=2))
    raise SystemExit(0)

passed = sum(1 for r in results.values() if r.overall_passed)
failed = sum(1 for r in results.values() if not r.overall_passed)

print()
print("=" * 92)
print(f"  DETERMINISTIC RUBRIC SCORER — Cloud Governance Scenario Eval v1.0")
print(f"  Scored {len(results)} scenarios → {passed} pass, {failed} fail")
print("=" * 92)

# Compact scorecard
print()
print(f"  {'sid':>4s}  {'result':>6s}  scenario rubric rationale")
print("  " + "-" * 86)
for sid in sorted(results.keys()):
    r = results[sid]
    status = "✓ PASS" if r.overall_passed else "✗ FAIL"
    rationale = (r.rubric_rationale or "").replace("\n", " ").strip()
    if len(rationale) > 70: rationale = rationale[:68] + ".."
    print(f"  {sid}    {status:>6s}  {rationale}")

# Detail on any failures
if failed > 0:
    print()
    print("=" * 92)
    print("  FAILURE DETAIL")
    print("=" * 92)
    for sid in sorted(results.keys()):
        r = results[sid]
        if r.overall_passed:
            continue
        print()
        print(f"  ----- SCENARIO {sid} — FAILED -----")
        print(f"    Rubric rationale: {r.rubric_rationale}")
        print(f"    Failed checks:")
        for c in r.checks:
            if c.passed:
                continue
            print(f"      ✗ {c.name:25s}  {c.message}")
            if c.name == "action_keywords" and c.detail:
                d = c.detail
                print(f"          └─ groups expected (any one keyword per group must match):")
                for i, g in enumerate(d.get("groups", [])):
                    matched = i in d.get("matched_group_indices", [])
                    flag = "✓" if matched else "✗"
                    keywords_short = ", ".join(g[:3]) + ("..." if len(g) > 3 else "")
                    print(f"             {flag} group {i}: [{keywords_short}]")
            elif c.name == "fixture_citation" and c.detail:
                d = c.detail
                print(f"          └─ fixture: {d.get('fixture')}")
                print(f"          └─ identifiers in metadata: {d.get('identifiers', [])[:5]}...")
                print(f"          └─ identifiers cited in recommendation: {d.get('cited', [])}")

# Verbose: per-check detail for ALL scenarios
if VERBOSE:
    print()
    print("=" * 92)
    print("  VERBOSE — every check for every scenario")
    print("=" * 92)
    for sid in sorted(results.keys()):
        r = results[sid]
        print()
        print(f"  ----- SCENARIO {sid} — {'PASS' if r.overall_passed else 'FAIL'} -----")
        for c in r.checks:
            flag = '✓' if c.passed else '✗'
            print(f"    {flag} {c.name:25s}  {c.message}")

print()
print("=" * 92)
print(f"  FINAL: {passed}/{len(results)} pass  ({'ALL PASS' if failed == 0 else f'{failed} fail(s)'})")
print("=" * 92)

# Exit non-zero if anything failed
raise SystemExit(0 if failed == 0 else 1)
PY

# ---- Execute the scorer ----
# pipefail (set above) makes python's exit code propagate through tee.
if [[ -n "$OUTPUT_FILE" ]]; then
  VERBOSE="$VERBOSE" EMIT_JSON="$EMIT_JSON" python3 "$PYSCRIPT" 2>&1 | tee "$OUTPUT_FILE"
else
  VERBOSE="$VERBOSE" EMIT_JSON="$EMIT_JSON" python3 "$PYSCRIPT"
fi
