#!/usr/bin/env bash
# ============================================================
# export_passing_scenarios.sh — Snapshot the public deliverable
# for all scenarios that have passed the full pipeline.
#
# A scenario is considered "passing" when:
#   - intermediates/NN/smoke_test_judge.json exists
#   - its judge outcome equals "pass"
# (i.e. it cleared all 5 pipeline phases AND the Haiku judge
# matched the spec's target recommendation.)
#
# Output: export/YYYYMMDD/
#   - scenarios/NN/    — public deliverable (metadata, terraform,
#                        4 tier telemetry files, correlation_evidence)
#   - smoke_tests/NN/  — Opus recommendation + judge verdict (audit trail)
#   - MANIFEST.md      — what's in this snapshot and when
#
# Usage:
#   scripts/export_passing_scenarios.sh
#       Auto-discover and export all "pass" scenarios.
#   scripts/export_passing_scenarios.sh --scenarios "01 10"
#       Export only the listed scenarios (skip auto-discovery).
#   scripts/export_passing_scenarios.sh --include-partial
#       Also include judge outcome=partial (default: pass only).
#   scripts/export_passing_scenarios.sh --dry-run
#       Print the plan, copy nothing.
#   scripts/export_passing_scenarios.sh -h | --help
#       This message.
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ALL_SCENARIO_IDS="01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18"

EXPLICIT_SCENARIOS=""
INCLUDE_PARTIAL=0
DRY_RUN=0

show_help() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --scenarios)
      [[ $# -ge 2 ]] || { echo "ERROR: --scenarios needs an argument" >&2; exit 2; }
      EXPLICIT_SCENARIOS="$2"; shift 2 ;;
    --include-partial) INCLUDE_PARTIAL=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

# ---- Discover the passing scenarios ----
PASSING=()
if [[ -n "$EXPLICIT_SCENARIOS" ]]; then
  read -ra PASSING <<< "$EXPLICIT_SCENARIOS"
  echo "Using explicit scenario list: ${PASSING[*]}"
else
  for sid in $ALL_SCENARIO_IDS; do
    judge="intermediates/$sid/smoke_test_judge.json"
    [[ ! -f "$judge" ]] && continue
    outcome=$(python3 -c "import json; print(json.loads(open('$judge').read()).get('outcome','?'))" 2>/dev/null || echo "?")
    if [[ "$outcome" == "pass" ]]; then
      PASSING+=("$sid")
    elif [[ "$outcome" == "partial" && "$INCLUDE_PARTIAL" == "1" ]]; then
      PASSING+=("$sid")
    fi
  done
fi

if [[ "${#PASSING[@]}" -eq 0 ]]; then
  echo "No passing scenarios found. (Use --scenarios to override auto-detect.)" >&2
  exit 1
fi

EXPORT_ROOT="export/$(date +%Y%m%d)"

# If today's export already exists, increment with a suffix so we don't clobber
if [[ -d "$EXPORT_ROOT" ]]; then
  suffix=2
  while [[ -d "${EXPORT_ROOT}_${suffix}" ]]; do
    suffix=$((suffix + 1))
  done
  EXPORT_ROOT="${EXPORT_ROOT}_${suffix}"
fi

echo "=========================================="
echo "  Export plan"
echo "=========================================="
echo "  Destination       : $EXPORT_ROOT"
echo "  Passing scenarios : ${PASSING[*]}"
echo "  Total count       : ${#PASSING[@]}"
echo "  Dry run           : $([[ "$DRY_RUN" == "1" ]] && echo yes || echo no)"
echo "=========================================="
echo ""

if [[ "$DRY_RUN" == "1" ]]; then
  for sid in "${PASSING[@]}"; do
    echo "  [dry-run] would export scenarios/$sid             → $EXPORT_ROOT/scenarios/$sid"
    echo "  [dry-run] would export intermediates/$sid/smoke_* → $EXPORT_ROOT/smoke_tests/$sid"
  done
  echo "  [dry-run] would write $EXPORT_ROOT/MANIFEST.md"
  exit 0
fi

mkdir -p "$EXPORT_ROOT/scenarios" "$EXPORT_ROOT/smoke_tests"

# ---- Copy ----
for sid in "${PASSING[@]}"; do
  src="scenarios/$sid"
  dst="$EXPORT_ROOT/scenarios/$sid"
  mkdir -p "$dst"
  for f in metadata.json main.tf correlation_evidence.json \
           compute_telemetry.json database_telemetry.json \
           cache_telemetry.json network_telemetry.json; do
    if [[ -f "$src/$f" ]]; then
      cp -p "$src/$f" "$dst/$f"
    else
      echo "  WARNING: $src/$f missing — skipping that file"
    fi
  done

  mkdir -p "$EXPORT_ROOT/smoke_tests/$sid"
  cp -p "intermediates/$sid/smoke_test.json"       "$EXPORT_ROOT/smoke_tests/$sid/"
  cp -p "intermediates/$sid/smoke_test_judge.json" "$EXPORT_ROOT/smoke_tests/$sid/"

  echo "  ✓ exported $sid"
done

# ---- Manifest ----
MANIFEST="$EXPORT_ROOT/MANIFEST.md"
{
  echo "# Export — $(date +%Y-%m-%d)"
  echo ""
  echo "Frozen snapshot of scenarios that passed the full data-gen pipeline"
  echo "(Pass 1 → Pass 2 → splitter → validate → smoke-test → judge) under"
  echo "the content-routing prompt revision."
  echo ""
  echo "Built by: scripts/export_passing_scenarios.sh"
  echo "When:     $(date)"
  echo ""
  echo "## Scenarios included (${#PASSING[@]})"
  echo ""
  for sid in "${PASSING[@]}"; do
    name=$(python3 -c "import yaml; print(yaml.safe_load(open('docs/internal/scenarios/$sid.spec.yaml'))['scenario_name'])" 2>/dev/null || echo "(unavailable)")
    echo "- \`$sid\` — $name"
  done
  echo ""
  echo "## Layout"
  echo ""
  echo "- \`scenarios/NN/\` — the public deliverable for scenario NN"
  echo "  (\`metadata.json\`, \`main.tf\`, 4 tier telemetry files, \`correlation_evidence.json\`)."
  echo "- \`smoke_tests/NN/\` — Opus recommendation + Haiku judge verdict for NN"
  echo "  (audit trail, not part of the consumer-facing dataset)."
} > "$MANIFEST"

# ---- Report ----
echo ""
echo "=========================================="
echo "  Export complete"
echo "=========================================="
echo "  Path : $EXPORT_ROOT"
echo "  Size : $(du -sh "$EXPORT_ROOT" | awk '{print $1}')"
echo ""
echo "  Files:"
find "$EXPORT_ROOT" -type f | sort | sed 's|^|    |'
