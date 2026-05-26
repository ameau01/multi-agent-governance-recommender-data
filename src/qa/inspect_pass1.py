"""Quick inspect tool for Pass 1 output.

Read-only, no LLM, no cost. Reads `intermediates/NN/pass1.json` and the
scenario spec, then prints:

  - Record counts per tier (expected 1344 for non-Scenario-5)
  - Timestamp coverage (first, last, gaps?)
  - Per-metric statistical summary (min, p50, p95, max, mean)
  - Spec-range conformance (% of records within declared metric ranges)
  - Weekday vs weekend comparison
  - Sample records (first 3, middle, last 3)

Usage:
    uv run python -m qa.inspect_pass1 01
    uv run python -m qa.inspect_pass1 07
"""

from __future__ import annotations
import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make src/ importable when invoked via `python -m`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generator.constants import (
    DATA_WINDOW_START_UTC,
    INTERMEDIATES_DIR,
    INTERVAL_MINUTES,
    RECORDS_PER_TIER,
)
from generator.spec_loader import load_spec


_TIER_KEYS = {
    "compute": "Compute_Metrics",
    "database": "Database_Metrics",
    "cache": "Cache_Metrics",
    "network": "Network_Metrics",
}

_WEEKEND_DATES = {"2026-05-02", "2026-05-03", "2026-05-09", "2026-05-10"}

_SEPARATOR = "─" * 78


def main() -> int:
    parser = argparse.ArgumentParser(prog="qa.inspect_pass1")
    parser.add_argument("scenario_id", help="Zero-padded scenario id, e.g. 01")
    parser.add_argument(
        "--intermediates",
        type=Path,
        default=INTERMEDIATES_DIR,
        help="Override intermediates directory",
    )
    args = parser.parse_args()

    scenario_id = args.scenario_id
    pass1_path = args.intermediates / scenario_id / "pass1.json"

    print(_SEPARATOR)
    print(f"  Pass 1 inspector — scenario {scenario_id}")
    print(_SEPARATOR)

    if not pass1_path.exists():
        print(f"\n  ✗ {pass1_path} does not exist.")
        print(f"     Pass 1 may not have completed for this scenario yet.")
        return 1

    pass1 = json.loads(pass1_path.read_text())
    try:
        spec = load_spec(scenario_id)
    except Exception as e:
        print(f"\n  ⚠ Could not load spec for {scenario_id}: {e}")
        print(f"    Continuing with structural checks only.")
        spec = None

    print(f"\n  File:  {pass1_path}")
    print(f"  Size:  {pass1_path.stat().st_size:,} bytes")
    print()

    # 1. Per-tier record counts + structural overview
    print("[1] Per-tier record counts")
    print(f"    {'tier':<12} {'records':>10} {'expected':>10} {'status':>10}")
    for tier_name, wire_key in _TIER_KEYS.items():
        records = pass1.get(wire_key, [])
        expected = _expected_records(scenario_id, tier_name, spec)
        present_in_spec = _tier_present_in_spec(spec, tier_name) if spec else None
        if expected == 0 and len(records) == 0:
            status = "—"
        elif len(records) == expected:
            status = "✓"
        else:
            status = "✗ MISMATCH"
        print(f"    {tier_name:<12} {len(records):>10,} {expected:>10,} {status:>10}")
    print()

    # 2. Detailed per-tier analysis for each active tier
    for tier_name, wire_key in _TIER_KEYS.items():
        records = pass1.get(wire_key, [])
        if not records:
            continue
        _inspect_tier(tier_name, records, spec)
        print()

    print(_SEPARATOR)
    print("  Inspection complete.")
    print(_SEPARATOR)
    return 0


def _inspect_tier(tier_name: str, records: list[dict[str, Any]], spec) -> None:
    """Detailed inspection of one tier's records."""
    print(_SEPARATOR)
    print(f"[2] Tier '{tier_name}' — {len(records):,} records")
    print(_SEPARATOR)

    # Timestamps
    timestamps = [r["timestamp"] for r in records]
    first_ts = timestamps[0]
    last_ts = timestamps[-1]
    print(f"  First timestamp:  {first_ts}")
    print(f"  Last  timestamp:  {last_ts}")
    print(f"  Total records:    {len(records):,}")

    # Check timestamp continuity
    gaps = _check_timestamp_gaps(timestamps)
    if gaps:
        print(f"  ✗ Timestamp gaps: {len(gaps)} found")
        for g in gaps[:5]:
            print(f"      gap at index {g['index']}: {g['expected']} → got {g['actual']}")
        if len(gaps) > 5:
            print(f"      ... ({len(gaps) - 5} more)")
    else:
        print(f"  ✓ Timestamps continuous (15-min intervals, no gaps)")

    # Per-metric statistics
    print()
    print(f"  Per-metric statistics:")
    numeric_keys = [
        k for k in records[0].keys()
        if k not in ("timestamp", "instance_id")
        and isinstance(records[0][k], (int, float))
    ]
    print(f"    {'metric':<32} {'min':>10} {'p50':>10} {'p95':>10} {'max':>10} {'mean':>10}")
    for k in numeric_keys:
        values = [r[k] for r in records if isinstance(r.get(k), (int, float))]
        if not values:
            continue
        sorted_v = sorted(values)
        n = len(sorted_v)
        p50 = sorted_v[n // 2]
        p95 = sorted_v[int(n * 0.95)]
        v_min = sorted_v[0]
        v_max = sorted_v[-1]
        mean_v = statistics.mean(values)
        print(f"    {k:<32} {v_min:>10.3f} {p50:>10.3f} {p95:>10.3f} {v_max:>10.3f} {mean_v:>10.3f}")

    # Spec-range conformance (if spec available)
    if spec is not None:
        _check_spec_conformance(tier_name, records, spec)

    # Weekday vs weekend split
    print()
    _weekday_weekend_summary(records, numeric_keys)

    # Sample records
    print()
    print(f"  Sample records:")
    for label, idx in [("first  ", 0), ("middle ", len(records) // 2), ("last   ", len(records) - 1)]:
        r = records[idx]
        # Truncate to fit
        compact = {k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()}
        compact_str = json.dumps(compact)
        if len(compact_str) > 140:
            compact_str = compact_str[:137] + "..."
        print(f"    [{label} #{idx:>4}]  {compact_str}")


def _check_timestamp_gaps(timestamps: list[str]) -> list[dict[str, Any]]:
    """Verify 15-min intervals starting at DATA_WINDOW_START_UTC."""
    from datetime import timedelta
    gaps: list[dict[str, Any]] = []
    expected = DATA_WINDOW_START_UTC
    for i, ts_str in enumerate(timestamps):
        ts = _parse_ts(ts_str)
        if ts != expected:
            gaps.append({"index": i, "expected": expected.isoformat(), "actual": ts.isoformat()})
        expected += timedelta(minutes=INTERVAL_MINUTES)
    return gaps


def _parse_ts(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _check_spec_conformance(tier_name: str, records: list[dict[str, Any]], spec) -> None:
    """For each metric with a declared range in the spec, count how many records fall inside."""
    pass1_metrics = spec.pass1_metrics or {}
    tier_metrics = pass1_metrics.get(tier_name)
    if not tier_metrics or not isinstance(tier_metrics, dict):
        return
    if tier_metrics.get("all_healthy"):
        print()
        print(f"  Spec range conformance: tier marked all_healthy (using healthy baselines)")
        return

    print()
    print(f"  Spec range conformance:")
    print(f"    {'metric':<32} {'declared_range':>22} {'in-range':>15} {'out-of-range':>15}")
    for metric_key, metric_spec in tier_metrics.items():
        if not isinstance(metric_spec, dict) or "range" not in metric_spec:
            continue
        rng = metric_spec["range"]
        if not (isinstance(rng, list) and len(rng) == 2):
            continue
        lo, hi = rng
        values = [r[metric_key] for r in records if isinstance(r.get(metric_key), (int, float))]
        if not values:
            continue
        in_range = sum(1 for v in values if lo <= v <= hi)
        out = len(values) - in_range
        pct_in = in_range / len(values) * 100
        marker = "✓" if pct_in >= 95 else "⚠" if pct_in >= 80 else "✗"
        print(
            f"    {metric_key:<32} {f'[{lo}, {hi}]':>22} "
            f"{f'{in_range} ({pct_in:.1f}%)':>15} {out:>15}  {marker}"
        )


def _weekday_weekend_summary(records: list[dict[str, Any]], numeric_keys: list[str]) -> None:
    """Compare weekday vs weekend averages."""
    weekday_records = []
    weekend_records = []
    for r in records:
        date_str = r["timestamp"][:10]
        if date_str in _WEEKEND_DATES:
            weekend_records.append(r)
        else:
            weekday_records.append(r)
    if not weekend_records or not weekday_records:
        return
    print(f"  Weekday ({len(weekday_records)} records) vs Weekend ({len(weekend_records)} records):")
    print(f"    {'metric':<32} {'weekday_mean':>14} {'weekend_mean':>14} {'ratio':>8}")
    for k in numeric_keys[:6]:  # cap at 6 metrics for readability
        wd_vals = [r[k] for r in weekday_records if isinstance(r.get(k), (int, float))]
        we_vals = [r[k] for r in weekend_records if isinstance(r.get(k), (int, float))]
        if not wd_vals or not we_vals:
            continue
        wd_m = statistics.mean(wd_vals)
        we_m = statistics.mean(we_vals)
        ratio = we_m / wd_m if wd_m else 0
        print(f"    {k:<32} {wd_m:>14.3f} {we_m:>14.3f} {ratio:>8.2f}")


def _expected_records(scenario_id: str, tier_name: str, spec) -> int:
    """How many records this tier should have for this scenario."""
    if spec is None:
        return RECORDS_PER_TIER if tier_name == "compute" else 0
    if not _tier_present_in_spec(spec, tier_name):
        return 0
    if scenario_id == "05" and tier_name == "compute":
        return 8 * RECORDS_PER_TIER
    return RECORDS_PER_TIER


def _tier_present_in_spec(spec, tier_name: str) -> bool:
    entry = spec.tier_topology.get(tier_name) if spec else None
    if not entry:
        return False
    return entry.get("present", True) is True


if __name__ == "__main__":
    sys.exit(main())
