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
#   scripts/export_passing_scenarios.sh --force
#       Overwrite today's export folder if it already exists.
#       Default behavior is to suffix with _2, _3, etc. on conflict.
#   scripts/export_passing_scenarios.sh --latest
#       Use the stable path `export/latest/` instead of a dated folder.
#       Merges per-scenario: each passing scenario's subfolder is
#       overwritten with current data, but pre-existing scenarios
#       NOT in the current passing set are preserved. This makes
#       `export/latest/` an accumulating "mini-repo" of all verified-
#       good scenarios across runs — copy this folder as-is into
#       any downstream project.
#   scripts/export_passing_scenarios.sh --use-deterministic
#       Use the deterministic rubric scorer (src/qa/deterministic_scorer.py)
#       to auto-detect passing scenarios instead of the Haiku LLM judge.
#       This is the recommended mode for HuggingFace publication — same
#       inputs produce identical scores every time.
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
FORCE=0
LATEST=0
USE_DETERMINISTIC=0

show_help() {
  sed -n '2,48p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --scenarios)
      [[ $# -ge 2 ]] || { echo "ERROR: --scenarios needs an argument" >&2; exit 2; }
      EXPLICIT_SCENARIOS="$2"; shift 2 ;;
    --include-partial) INCLUDE_PARTIAL=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --latest) LATEST=1; shift ;;
    --use-deterministic) USE_DETERMINISTIC=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

if [[ "$LATEST" == "1" && "$FORCE" == "1" ]]; then
  echo "Note: --latest implies merge semantics; --force is ignored." >&2
fi

# ---- Discover the passing scenarios ----
# Three sources, in priority order:
#   1. Explicit --scenarios list (overrides everything)
#   2. --use-deterministic: pass = deterministic_scorer.overall_passed
#   3. Default: pass = Haiku judge outcome (with --include-partial widening)
PASSING=()
if [[ -n "$EXPLICIT_SCENARIOS" ]]; then
  read -ra PASSING <<< "$EXPLICIT_SCENARIOS"
  echo "Using explicit scenario list: ${PASSING[*]}"
elif [[ "$USE_DETERMINISTIC" == "1" ]]; then
  echo "Auto-detecting passing scenarios via deterministic rubric scorer..."
  export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
  # Run the scorer once and capture the IDs whose overall_passed=true
  PASSING_STR=$(ALL_SCENARIO_IDS="$ALL_SCENARIO_IDS" python3 <<'PY'
import json, os
from pathlib import Path
from qa.deterministic_scorer import score_all
results = score_all(Path("intermediates"), Path("scenarios"))
passing_ids = [sid for sid, r in sorted(results.items()) if r.overall_passed]
print(" ".join(passing_ids))
PY
  )
  read -ra PASSING <<< "$PASSING_STR"
  echo "  Deterministic scorer found ${#PASSING[@]} passing scenario(s): ${PASSING[*]}"
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

if [[ "$LATEST" == "1" ]]; then
  # Stable accumulating path. Per-scenario folders are overwritten in this run;
  # pre-existing scenarios NOT in the current passing set are preserved as-is.
  EXPORT_ROOT="export/latest"
  MERGE_MODE="latest (merge — preserves pre-existing scenarios)"
elif [[ -d "export/$(date +%Y%m%d)" ]]; then
  EXPORT_ROOT="export/$(date +%Y%m%d)"
  if [[ "$FORCE" == "1" ]]; then
    echo "  Note: $EXPORT_ROOT exists — --force enabled, will overwrite contents."
    if [[ "$DRY_RUN" != "1" ]]; then
      # Remove only the auto-managed sub-paths; leave any user-added siblings.
      rm -rf "$EXPORT_ROOT/scenarios" "$EXPORT_ROOT/smoke_tests" "$EXPORT_ROOT/MANIFEST.md"
    fi
    MERGE_MODE="dated (--force overwrite)"
  else
    suffix=2
    while [[ -d "${EXPORT_ROOT}_${suffix}" ]]; do
      suffix=$((suffix + 1))
    done
    EXPORT_ROOT="${EXPORT_ROOT}_${suffix}"
    echo "  Note: today's export already existed; using $EXPORT_ROOT (use --force to overwrite, or --latest for merge)."
    MERGE_MODE="dated (auto-suffix)"
  fi
else
  EXPORT_ROOT="export/$(date +%Y%m%d)"
  MERGE_MODE="dated (new folder)"
fi

echo "=========================================="
echo "  Export plan"
echo "=========================================="
echo "  Destination       : $EXPORT_ROOT"
echo "  Mode              : $MERGE_MODE"
echo "  Passing scenarios : ${PASSING[*]}"
echo "  Total count       : ${#PASSING[@]}"
echo "  Dry run           : $([[ "$DRY_RUN" == "1" ]] && echo yes || echo no)"
if [[ "$LATEST" == "1" && -d "$EXPORT_ROOT/scenarios" ]]; then
  # Show what's already there that won't be touched in this run.
  # (Avoid bash-only <(...) process substitution so the script tolerates being
  # invoked as `sh script.sh` in addition to `bash script.sh`.)
  PRESERVED=""
  for d in "$EXPORT_ROOT/scenarios"/*/; do
    [[ -d "$d" ]] || continue
    existing_sid=$(basename "$d")
    found=0
    for psid in "${PASSING[@]}"; do
      if [[ "$psid" == "$existing_sid" ]]; then
        found=1
        break
      fi
    done
    if [[ "$found" == "0" ]]; then
      PRESERVED="$PRESERVED $existing_sid"
    fi
  done
  PRESERVED=$(echo "$PRESERVED" | sed 's/^ //;s/ $//')
  if [[ -n "$PRESERVED" ]]; then
    echo "  Preserved (from previous runs): $PRESERVED"
  fi
fi
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

# ---- Manifest builders ----
# Generate three artifacts at the export root:
#   1. INDEX.json   — machine-readable summary (schema version, per-scenario
#                     facts, layout pointers). Downstream consumers parse this.
#   2. MANIFEST.md  — human-readable summary with the same data plus context.
#   3. README.md    — short top-level entry point, points readers at the other
#                     two. Stable across runs.
#
# All three are regenerated atomically at the end of every export run so they
# always reflect the current folder state (this run's exports + any pre-existing
# scenarios preserved in --latest mode).
#
# Implementation: a single python3 invocation that reads each scenario's
# metadata.json + smoke_test_judge.json from the export folder and writes the
# three files. Uses ONLY the stdlib json module — no PyYAML or external deps.

# Build the list of all scenarios currently present in the export folder.
ALL_PRESENT=()
if [[ -d "$EXPORT_ROOT/scenarios" ]]; then
  for d in "$EXPORT_ROOT/scenarios"/*/; do
    [[ -d "$d" ]] || continue
    ALL_PRESENT+=("$(basename "$d")")
  done
fi
# Sort them
ALL_PRESENT_SORTED=$(printf '%s\n' "${ALL_PRESENT[@]}" | sort -u | tr '\n' ' ')

# Convert PASSING (this run's set) to a space-separated string for python.
CURRENT_RUN_STR=$(printf '%s ' "${PASSING[@]}")

# Pass mode info through to python
MODE_LABEL=$([[ "$LATEST" == "1" ]] && echo "latest" || echo "dated")

EXPORT_ROOT_REL="$EXPORT_ROOT" \
ALL_PRESENT_STR="$ALL_PRESENT_SORTED" \
CURRENT_RUN_STR="$CURRENT_RUN_STR" \
MODE_LABEL="$MODE_LABEL" \
python3 <<'PY'
import json, os, sys, datetime

EXPORT_ROOT = os.environ["EXPORT_ROOT_REL"]
PRESENT = [s for s in os.environ["ALL_PRESENT_STR"].split() if s]
CURRENT_RUN = set(s for s in os.environ["CURRENT_RUN_STR"].split() if s)
MODE = os.environ["MODE_LABEL"]

SCHEMA_VERSION = "1.0"
BUILT_AT = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
BUILT_LOCAL = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z").strip()

LAYOUT = {
    "scenarios/NN/metadata.json":          "Scenario metadata: narrative, business_context, "
                                            "cost_baseline, tier_topology, target_recommendation, "
                                            "evaluation_properties. Validated by contracts.ScenarioMetadata.",
    "scenarios/NN/main.tf":                 "Terraform HCL infrastructure definition for the scenario. "
                                            "Defines aws_instance / aws_db_instance / aws_elasticache_cluster / "
                                            "aws_lb resources matching the metadata's tier_topology.",
    "scenarios/NN/compute_telemetry.json":  "1,344 records (14 days × 96 intervals/day) for compute tier. "
                                            "Validated by contracts.ComputeRecord (array). Empty [] if "
                                            "scenario is not compute-bearing.",
    "scenarios/NN/database_telemetry.json": "Same as compute_telemetry.json but for database tier. "
                                            "Validated by contracts.DatabaseRecord (array).",
    "scenarios/NN/cache_telemetry.json":    "Same shape for cache tier. Validated by contracts.CacheRecord (array).",
    "scenarios/NN/network_telemetry.json":  "Same shape for network tier. Validated by contracts.NetworkRecord (array).",
    "scenarios/NN/correlation_evidence.json": "Cross-tier correlation pairs (Pearson coefficient + lag) when "
                                              "the scenario's pass2_correlations rules produce coupling. "
                                              "Empty [] if no correlations apply.",
    "smoke_tests/NN/smoke_test.json":       "Opus rich-schema recommendation (conclusion, evidence, "
                                            "reasoning, projected_state, cost_impact, risk_assessment). "
                                            "Per docs/internal/agent_recommendation_template.md.",
    "smoke_tests/NN/smoke_test_judge.json": "Haiku LLM-as-judge field-by-field comparison vs the spec's "
                                            "target_recommendation. Pass/partial/fail outcome.",
}

# --- Build per-scenario summary ---
scenarios = []
total_records = {"compute": 0, "database": 0, "cache": 0, "network": 0}

for sid in PRESENT:
    meta_path  = os.path.join(EXPORT_ROOT, "scenarios", sid, "metadata.json")
    judge_path = os.path.join(EXPORT_ROOT, "smoke_tests", sid, "smoke_test_judge.json")
    corr_path  = os.path.join(EXPORT_ROOT, "scenarios", sid, "correlation_evidence.json")

    try:
        meta = json.loads(open(meta_path).read())
    except Exception:
        meta = {}
    try:
        judge = json.loads(open(judge_path).read())
    except Exception:
        judge = {}
    try:
        correlations = json.loads(open(corr_path).read())
    except Exception:
        correlations = []

    rec_counts = {}
    tiers_present = []
    for tier in ("compute", "database", "cache", "network"):
        f = os.path.join(EXPORT_ROOT, "scenarios", sid, f"{tier}_telemetry.json")
        try:
            arr = json.loads(open(f).read())
        except Exception:
            arr = []
        n = len(arr) if isinstance(arr, list) else 0
        rec_counts[tier] = n
        total_records[tier] += n
        if n > 0:
            tiers_present.append(tier)

    scenarios.append({
        "id": sid,
        "name": meta.get("scenario_name", "(unavailable)"),
        "type": meta.get("scenario_type", "(unavailable)"),
        "criticality": (meta.get("business_context") or {}).get("criticality"),
        "sla_target_p95_ms": (meta.get("business_context") or {}).get("sla_target_p95_ms"),
        "monthly_cost_total_usd": (meta.get("cost_baseline") or {}).get("monthly_cost_total_usd"),
        "tiers_present": tiers_present,
        "record_counts": rec_counts,
        "has_correlation_evidence": len(correlations) > 0,
        "correlation_pairs_count": len(correlations) if isinstance(correlations, list) else 0,
        "judge_outcome": judge.get("outcome"),
        "judge_matches": {
            field: (judge.get(field) or {}).get("match", False)
            for field in ("finding_type", "primary_tier", "action_category", "specific_change")
        },
        "refreshed_in_this_run": sid in CURRENT_RUN,
    })

# --- INDEX.json (machine-readable) ---
index = {
    "schema_version":   SCHEMA_VERSION,
    "export_mode":      MODE,
    "built_at_utc":     BUILT_AT,
    "built_by":         "scripts/export_passing_scenarios.sh",
    "source_repo":      "multi-agent-governance-recommender-data",
    "total_scenarios":  len(scenarios),
    "total_records":    total_records,
    "scenarios":        scenarios,
    "layout":           LAYOUT,
    "pydantic_models":  {
        "metadata.json":            "contracts.ScenarioMetadata",
        "compute_telemetry.json":   "contracts.ComputeRecord (list)",
        "database_telemetry.json":  "contracts.DatabaseRecord (list)",
        "cache_telemetry.json":     "contracts.CacheRecord (list)",
        "network_telemetry.json":   "contracts.NetworkRecord (list)",
        "correlation_evidence.json": "contracts.CorrelationPair (list)",
        "smoke_test.json":          "qa.smoke_test.SmokeTestRecommendation",
        "smoke_test_judge.json":    "qa.smoke_test.SmokeTestJudgeResult",
    },
    "outcomes_distribution": {
        "pass":    sum(1 for s in scenarios if s["judge_outcome"] == "pass"),
        "partial": sum(1 for s in scenarios if s["judge_outcome"] == "partial"),
        "fail":    sum(1 for s in scenarios if s["judge_outcome"] == "fail"),
        "other":   sum(1 for s in scenarios if s["judge_outcome"] not in ("pass","partial","fail")),
    },
}
with open(os.path.join(EXPORT_ROOT, "INDEX.json"), "w") as f:
    json.dump(index, f, indent=2)

# --- MANIFEST.md (human-readable) ---
md = []
md.append(f"# {'`export/latest/`' if MODE=='latest' else 'Export — ' + BUILT_AT[:10]} — Cloud Governance Scenario Dataset")
md.append("")
md.append(f"**Schema version:** `{SCHEMA_VERSION}`")
md.append(f"**Built at:** `{BUILT_LOCAL or BUILT_AT}`")
md.append(f"**Built by:** `scripts/export_passing_scenarios.sh`")
md.append(f"**Source repo:** `multi-agent-governance-recommender-data`")
md.append(f"**Mode:** `{MODE}` " + ("(accumulating mini-repo — merge per-scenario, preserves earlier runs)" if MODE == "latest" else "(dated snapshot — frozen point-in-time)"))
md.append("")
md.append(f"## Summary")
md.append("")
md.append(f"- Total scenarios: **{len(scenarios)}**")
od = index["outcomes_distribution"]
md.append(f"- Judge outcomes: pass=**{od['pass']}**, partial=**{od['partial']}**, fail=**{od['fail']}**")
md.append(f"- Total records:")
for tier in ("compute","database","cache","network"):
    md.append(f"    - {tier}: **{total_records[tier]:,}** records across {sum(1 for s in scenarios if s['record_counts'][tier]>0)} scenario(s)")
md.append("")
md.append(f"## Scenarios")
md.append("")
md.append(f"| ID | Name | Type | Criticality | Tiers present | Correlations | Judge |")
md.append(f"|---|---|---|---|---|---|---|")
for s in scenarios:
    tiers = ",".join(s["tiers_present"]) or "—"
    corrs = "✓" if s["has_correlation_evidence"] else "—"
    outcome = s["judge_outcome"] or "—"
    md.append(f"| `{s['id']}` | {s['name']} | `{s['type']}` | {s['criticality'] or '—'} | {tiers} | {corrs} | `{outcome}` |")
md.append("")
md.append(f"## Field match per scenario (vs. spec target_recommendation)")
md.append("")
md.append(f"| ID | finding_type | primary_tier | action_category | specific_change |")
md.append(f"|---|---|---|---|---|")
for s in scenarios:
    m = s["judge_matches"]
    cells = " | ".join("✓" if m[f] else "✗" for f in ("finding_type","primary_tier","action_category","specific_change"))
    md.append(f"| `{s['id']}` | {cells} |")
md.append("")
md.append(f"## Layout")
md.append("")
for path, desc in LAYOUT.items():
    md.append(f"- **`{path}`** — {desc}")
md.append("")
md.append(f"## Pydantic models for downstream validation")
md.append("")
md.append(f"Each JSON file in this export maps to a Pydantic model in the source repo's `src/contracts/` package. To validate as you load:")
md.append(f"")
md.append(f"```python")
md.append(f"from contracts import ScenarioMetadata, ComputeRecord, ...")
md.append(f"metadata = ScenarioMetadata.model_validate(json.load(open('scenarios/01/metadata.json')))")
md.append(f"records  = [ComputeRecord.model_validate(r) for r in json.load(open('scenarios/01/compute_telemetry.json'))]")
md.append(f"```")
md.append("")
md.append(f"For machine consumption, parse `INDEX.json` instead of this file — it carries the same data in a stable JSON shape.")
md.append("")
with open(os.path.join(EXPORT_ROOT, "MANIFEST.md"), "w") as f:
    f.write("\n".join(md))

# --- README.md (top-level entry point) ---
readme = []
readme.append(f"# Cloud Governance Scenario Dataset")
readme.append("")
readme.append(f"Drop-in dataset of {len(scenarios)} cloud-application scenarios for downstream cloud-governance agents.")
readme.append(f"Each scenario carries 14 days of synthetic telemetry across up to 4 tiers, plus the infrastructure")
readme.append(f"definition (Terraform), scenario metadata (business context, SLA, cost baseline), and a reference")
readme.append(f"recommendation produced by Claude Opus 4.6 against the same data.")
readme.append("")
readme.append(f"**Read first:**")
readme.append(f"")
readme.append(f"- [`MANIFEST.md`](MANIFEST.md) — human-readable summary and schema documentation.")
readme.append(f"- [`INDEX.json`](INDEX.json) — machine-readable per-scenario index; parse this in code.")
readme.append("")
readme.append(f"**Quick stats:**")
readme.append(f"")
readme.append(f"- Schema version: **{SCHEMA_VERSION}**")
readme.append(f"- Scenarios: **{len(scenarios)}** ({od['pass']} pass, {od['partial']} partial, {od['fail']} fail)")
readme.append(f"- Total telemetry records: **{sum(total_records.values()):,}**")
readme.append(f"")
readme.append(f"Built `{BUILT_LOCAL or BUILT_AT}` by `scripts/export_passing_scenarios.sh` from `multi-agent-governance-recommender-data`.")
readme.append("")
with open(os.path.join(EXPORT_ROOT, "README.md"), "w") as f:
    f.write("\n".join(readme))

print(f"  ✓ wrote {EXPORT_ROOT}/INDEX.json")
print(f"  ✓ wrote {EXPORT_ROOT}/MANIFEST.md")
print(f"  ✓ wrote {EXPORT_ROOT}/README.md")
PY

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
