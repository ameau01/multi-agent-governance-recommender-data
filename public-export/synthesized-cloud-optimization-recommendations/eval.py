"""Floor sanity check for the synthesized cloud-optimization recommendations dataset.

This is a minimal check. It reads your predictions file and confirms:
    1. Each prediction parses as JSON.
    2. Required fields are present.
    3. finding_type is one of the three allowed values.
    4. primary_tier is one of the allowed tier names (or null).
    5. specific_change is a non-empty string of reasonable length.

For full Floor + Mid + Rich scoring, see the companion eval-set in the same
Hugging Face repository.

Usage:
    python eval.py --predictions sample_predictions.json
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


REQUIRED_FIELDS = ["scenario_id", "finding_type", "specific_change",
                   "primary_tier", "action_category"]

ALLOWED_FINDING_TYPES = {"issue_found", "no_issue_found", "diagnostic_deferral"}
ALLOWED_TIERS = {"compute", "database", "cache", "network", None}
ALLOWED_ACTION_CATEGORIES = {
    "rightsizing", "scaling_policy_change", "query_cache_optimization",
    "pool_sizing", "replica_adjustment", "load_balancer_reconfiguration",
    "network_topology_change", "sla_review", None,
}


def check_one(prediction: dict) -> list[str]:
    """Return a list of error messages. Empty list means the prediction passes."""
    errors = []
    sid = prediction.get("scenario_id", "?")
    for f in REQUIRED_FIELDS:
        if f not in prediction:
            errors.append(f"scenario {sid}: missing required field {f!r}")

    ft = prediction.get("finding_type")
    if ft not in ALLOWED_FINDING_TYPES:
        errors.append(f"scenario {sid}: finding_type {ft!r} not in {sorted(ALLOWED_FINDING_TYPES)}")

    pt = prediction.get("primary_tier")
    if pt not in ALLOWED_TIERS:
        errors.append(f"scenario {sid}: primary_tier {pt!r} not in {sorted(t for t in ALLOWED_TIERS if t)}")

    ac = prediction.get("action_category")
    if ac not in ALLOWED_ACTION_CATEGORIES:
        errors.append(f"scenario {sid}: action_category {ac!r} not allowed")

    sc = prediction.get("specific_change") or ""
    if len(sc.strip()) < 20:
        errors.append(f"scenario {sid}: specific_change too short ({len(sc.strip())} chars, need >=20)")

    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True, type=Path,
                    help="path to predictions JSON file")
    args = ap.parse_args()

    if not args.predictions.exists():
        print(f"ERROR: file not found: {args.predictions}", file=sys.stderr)
        sys.exit(2)

    doc = json.loads(args.predictions.read_text())
    preds = doc.get("predictions", [])

    if not preds:
        print("ERROR: predictions file has no 'predictions' array", file=sys.stderr)
        sys.exit(2)

    print()
    print("=" * 70)
    print(f"  Floor sanity check: {len(preds)} prediction(s)")
    print("=" * 70)

    total_errors = 0
    for p in preds:
        errs = check_one(p)
        sid = p.get("scenario_id", "?")
        if errs:
            print(f"  ✗ {sid}: {len(errs)} problem(s)")
            for e in errs:
                print(f"      {e}")
            total_errors += len(errs)
        else:
            print(f"  ✓ {sid}: parseable and on-topic")

    print()
    if total_errors == 0:
        print(f"  All {len(preds)} prediction(s) passed the Floor sanity check.")
        print("  For full Floor + Mid + Rich scoring, see the companion eval-set.")
        sys.exit(0)
    else:
        print(f"  {total_errors} problem(s) across the predictions file.")
        sys.exit(1)


if __name__ == "__main__":
    main()
