"""Score a predictions file against the cloud-governance expectations.

Usage:
    python eval.py --predictions PATH --dataset PATH [--tier all|floor|mid|rich]

Inputs:
    --predictions    path to your predictions JSON file
    --dataset        path to the dataset folder (sibling of this folder, or
                     a clone of just the dataset folder)
    --tier           which tier to report on. Default: all
    --json           emit machine-readable JSON to stdout

Predictions file shape:
    {
      "predictions": [
        {
          "scenario_id": "01",
          "finding_type": "issue_found",
          "specific_change": "...",
          "primary_tier": "compute",
          "secondary_tier": null,
          "action_category": "rightsizing",
          "reasoning": "...",
          "evidence": { ... },
          "projected_state": { ... },
          "cost_impact": { ... },
          "risk_assessment": { ... }
        },
        ...
      ]
    }

See sample_predictions.json for a worked example.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Local import (tiers.py is a sibling)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tiers import score_floor, score_mid, score_rich  # noqa: E402


def load_predictions(path: Path) -> dict[str, dict]:
    """Read a predictions file and key it by scenario_id."""
    doc = json.loads(path.read_text())
    preds = doc.get("predictions", [])
    by_id = {}
    for p in preds:
        sid = p.get("scenario_id")
        if not sid:
            continue
        by_id[sid] = p
    return by_id


def load_expectations(sid: str) -> dict:
    path = HERE / "expectations" / sid / "evaluation_expectations.json"
    return json.loads(path.read_text())


def load_scenario_metadata(dataset_dir: Path, sid: str) -> dict | None:
    """Load the scenario metadata if available. Needed for fixture checks."""
    path = dataset_dir / "scenarios" / sid / "metadata.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def score_one(prediction: dict, expectations: dict,
              metadata: dict | None, tier: str) -> dict:
    """Score one prediction at the requested tier(s)."""
    out = {}
    if tier in ("all", "floor"):
        out["floor"] = score_floor(prediction, expectations)
    if tier in ("all", "mid"):
        out["mid"] = score_mid(prediction, expectations)
    if tier in ("all", "rich"):
        out["rich"] = score_rich(prediction, expectations, metadata)
    return out


def print_compact(results: dict) -> None:
    """Per-scenario scorecard."""
    print()
    print("=" * 78)
    print(f"  {'sid':>4s}  {'floor':>6s}  {'mid':>6s}  {'rich':>6s}  notes")
    print("  " + "-" * 72)
    for sid in sorted(results.keys()):
        r = results[sid]
        if r.get("error"):
            print(f"  {sid}    {r['error']}")
            continue
        floor = "PASS" if r.get("floor", _none()).passed else "FAIL"
        mid = "PASS" if r.get("mid", _none()).passed else "FAIL"
        rich = "PASS" if r.get("rich", _none()).passed else "FAIL"
        # Compact failure note
        notes = []
        for tier_name in ("floor", "mid", "rich"):
            tr = r.get(tier_name)
            if tr and not tr.passed:
                bad = [c.name for c in tr.checks if not c.passed]
                if bad:
                    notes.append(f"{tier_name}:{','.join(bad)}")
        note = "; ".join(notes) if notes else ""
        print(f"  {sid}    {floor:>6s}  {mid:>6s}  {rich:>6s}  {note}")


def _none():
    class N:
        passed = True
        checks = []
    return N()


def summarize(results: dict) -> dict:
    """Aggregate pass counts per tier."""
    totals = {"floor": 0, "mid": 0, "rich": 0, "n": len(results)}
    for r in results.values():
        if r.get("error"):
            continue
        for tier in ("floor", "mid", "rich"):
            tr = r.get(tier)
            if tr and tr.passed:
                totals[tier] += 1
    return totals


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True, type=Path,
                    help="path to predictions JSON")
    ap.add_argument("--dataset", required=True, type=Path,
                    help="path to dataset folder (contains scenarios/NN/metadata.json)")
    ap.add_argument("--tier", default="all", choices=("all", "floor", "mid", "rich"))
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    args = ap.parse_args()

    if not args.predictions.exists():
        print(f"ERROR: predictions file not found: {args.predictions}", file=sys.stderr)
        sys.exit(2)
    if not args.dataset.is_dir():
        print(f"ERROR: dataset dir not found: {args.dataset}", file=sys.stderr)
        sys.exit(2)

    preds = load_predictions(args.predictions)

    results: dict[str, dict] = {}
    expectations_root = HERE / "expectations"
    sids = sorted([p.name for p in expectations_root.iterdir() if p.is_dir()])
    for sid in sids:
        if sid not in preds:
            results[sid] = {"error": "no prediction submitted"}
            continue
        exp = load_expectations(sid)
        meta = load_scenario_metadata(args.dataset, sid)
        results[sid] = score_one(preds[sid], exp, meta, args.tier)

    totals = summarize(results)

    if args.json:
        out = {}
        for sid, r in results.items():
            if r.get("error"):
                out[sid] = {"error": r["error"]}
                continue
            out[sid] = {
                tier: tr.to_dict() for tier, tr in r.items()
            }
        out["_totals"] = totals
        print(json.dumps(out, indent=2))
    else:
        print_compact(results)
        print()
        print(f"  Totals: floor {totals['floor']}/{totals['n']}  "
              f"mid {totals['mid']}/{totals['n']}  "
              f"rich {totals['rich']}/{totals['n']}")
        print("=" * 78)

    # Exit code: 0 if everything submitted passed every requested tier
    failed = 0
    for r in results.values():
        if r.get("error"):
            failed += 1
            continue
        for tier_name, tr in r.items():
            if hasattr(tr, "passed") and not tr.passed:
                failed += 1
                break
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
