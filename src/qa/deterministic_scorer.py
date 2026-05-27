"""Deterministic rubric-based scoring for cloud-governance recommendations.

Replaces the Haiku LLM-as-judge with pure-Python checks against per-scenario
rubrics defined in `rubrics.py`. Same recommendation + same rubric → byte-
identical score, every time, in any environment.

Public API:

    score_recommendation(scenario_id, recommendation, scenario_metadata) → ScoreResult

Where:
    scenario_id : "01" through "18"
    recommendation : dict — the agent's output, MUST contain at minimum
        finding_type, specific_change. May contain primary_tier,
        secondary_tier, action_category, and the rich sections.
    scenario_metadata : dict — the scenarios/NN/metadata.json content
        (needed for fixture-citation checks against scenario_specific_evidence).

This module has NO Anthropic SDK dependency and makes NO network calls.
It can be lifted into any downstream project that wants to evaluate
predictions against this dataset's rubrics.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any

from qa.rubrics import RUBRICS, get_rubric


# ============================================================
# Result types
# ============================================================
@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreResult:
    scenario_id: str
    overall_passed: bool                 # all REQUIRED checks passed
    checks: list[CheckResult]
    rubric_rationale: str = ""           # the scenario-level _rationale from rubric

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "overall_passed": self.overall_passed,
            "rubric_rationale": self.rubric_rationale,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message,
                 "detail": c.detail}
                for c in self.checks
            ],
        }


# ============================================================
# Public entry point
# ============================================================
def score_recommendation(
    scenario_id: str,
    recommendation: dict,
    scenario_metadata: dict | None = None,
) -> ScoreResult:
    """Score one recommendation against its scenario's rubric.

    Args:
        scenario_id: e.g. "01".
        recommendation: agent's prediction. Must include `finding_type` and
            `specific_change`. May include `primary_tier`, `secondary_tier`,
            `action_category`, etc.
        scenario_metadata: scenarios/NN/metadata.json content; needed for
            fixture-citation checks. If None, fixture-citation checks are
            skipped (with a warning in the check result).

    Returns:
        ScoreResult — `overall_passed` is True iff every check below passed.
    """
    rubric = get_rubric(scenario_id)
    if rubric is None:
        return ScoreResult(
            scenario_id=scenario_id,
            overall_passed=False,
            checks=[CheckResult(
                name="rubric_loaded", passed=False,
                message=f"No rubric defined for scenario {scenario_id}",
            )],
        )

    checks: list[CheckResult] = []
    text = (recommendation.get("specific_change") or "").lower()

    # ----- 1. finding_type -----
    if "finding_type_allowed" in rubric:
        allowed = rubric["finding_type_allowed"]
        actual = recommendation.get("finding_type")
        checks.append(CheckResult(
            name="finding_type",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # ----- 2. primary_tier -----
    if "primary_tier_allowed" in rubric:
        allowed = rubric["primary_tier_allowed"]
        actual = recommendation.get("primary_tier")
        checks.append(CheckResult(
            name="primary_tier",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # ----- 3. secondary_tier (optional check) -----
    if "secondary_tier_allowed" in rubric:
        allowed = rubric["secondary_tier_allowed"]
        actual = recommendation.get("secondary_tier")
        checks.append(CheckResult(
            name="secondary_tier",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # ----- 4. action_category -----
    if "action_category_allowed" in rubric:
        allowed = rubric["action_category_allowed"]
        actual = recommendation.get("action_category")
        checks.append(CheckResult(
            name="action_category",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # ----- 5. Action keyword groups (OR-groups; need at least min_match) -----
    if "action_keyword_groups" in rubric:
        groups = rubric["action_keyword_groups"]
        min_match = rubric.get("action_keyword_min_match", len(groups))
        matched_groups = []
        for i, group in enumerate(groups):
            if any(kw.lower() in text for kw in group):
                matched_groups.append(i)
        passed = len(matched_groups) >= min_match
        checks.append(CheckResult(
            name="action_keywords",
            passed=passed,
            message=(
                f"matched {len(matched_groups)}/{len(groups)} keyword groups "
                f"(need {min_match})"
            ),
            detail={
                "groups": groups,
                "matched_group_indices": matched_groups,
                "min_match": min_match,
            },
        ))

    # ----- 6. Multi-tier evidence -----
    if "multi_tier_evidence" in rubric:
        mt = rubric["multi_tier_evidence"]
        required = mt["must_cite_tiers"]
        min_tiers = mt.get("min_tiers", len(required))
        # Also check evidence.* and reasoning sections, not just specific_change
        full_text = text + " " + (recommendation.get("reasoning") or "").lower()
        if recommendation.get("evidence"):
            for cat in ("telemetry_observations", "infrastructure_context",
                        "correlation_observations"):
                for bullet in (recommendation["evidence"].get(cat) or []):
                    full_text += " " + bullet.lower()
        mentioned = [t for t in required if t in full_text]
        passed = len(mentioned) >= min_tiers
        checks.append(CheckResult(
            name="multi_tier_evidence",
            passed=passed,
            message=(
                f"mentioned tiers: {mentioned} of {required} "
                f"(need ≥{min_tiers})"
            ),
            detail={
                "required_tiers": required,
                "mentioned_tiers": mentioned,
                "min_tiers": min_tiers,
            },
        ))

    # ----- 7. Fixture citation -----
    if "must_cite_fixture" in rubric and scenario_metadata is not None:
        fixture_name = rubric["must_cite_fixture"]
        evidence = scenario_metadata.get("scenario_specific_evidence", {}) or {}
        items = evidence.get(fixture_name, []) or []
        # Extract identifier strings from each fixture entry
        identifiers = _extract_fixture_identifiers(fixture_name, items)
        if not identifiers:
            # Fixture is empty in metadata — skip the check (not the agent's fault)
            checks.append(CheckResult(
                name="fixture_citation",
                passed=True,
                message=f"skipped — {fixture_name} is empty in metadata",
            ))
        else:
            full_text = text + " " + (recommendation.get("reasoning") or "").lower()
            if recommendation.get("evidence"):
                for cat in ("telemetry_observations", "infrastructure_context"):
                    for bullet in (recommendation["evidence"].get(cat) or []):
                        full_text += " " + bullet.lower()
            cited = [i for i in identifiers if i.lower() in full_text]
            passed = len(cited) >= 1
            checks.append(CheckResult(
                name="fixture_citation",
                passed=passed,
                message=(
                    f"cited {len(cited)}/{len(identifiers)} {fixture_name} "
                    f"identifiers (need ≥1)"
                ),
                detail={
                    "fixture": fixture_name,
                    "identifiers": identifiers,
                    "cited": cited,
                },
            ))

    overall = all(c.passed for c in checks)
    return ScoreResult(
        scenario_id=scenario_id,
        overall_passed=overall,
        checks=checks,
        rubric_rationale=rubric.get("_rationale", ""),
    )


# ============================================================
# Fixture identifier extraction
# ============================================================
def _extract_fixture_identifiers(fixture_name: str, items: list) -> list[str]:
    """Pull the identifier string from each fixture entry."""
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            if isinstance(item, str):
                out.append(item)
            continue
        if fixture_name == "top_queries":
            # Entries look like: {"name": "users_by_email_lookup", "p95_latency_ms": 340}
            # or {"query": "...", "shorthand": "..."}
            for key in ("name", "shorthand", "query_name", "id"):
                if key in item and isinstance(item[key], str):
                    out.append(item[key])
                    break
        elif fixture_name == "top_cache_keys":
            # Entries look like: "rec:user:*" or {"pattern": "rec:user:*"}
            for key in ("pattern", "key", "name"):
                if key in item and isinstance(item[key], str):
                    out.append(item[key])
                    break
        elif fixture_name == "per_instance_breakdown":
            # Entries look like: {"instance_id": "i-001", "cpu_band": "78-88% (hot)"}
            if "instance_id" in item:
                out.append(item["instance_id"])
    return out


# ============================================================
# Bulk scorer — score every scenario that has a smoke_test.json
# ============================================================
def score_all(
    intermediates_dir,
    scenarios_dir,
) -> dict[str, ScoreResult]:
    """Run the deterministic scorer against every scenario's existing smoke_test.json.

    Args:
        intermediates_dir: e.g. Path("intermediates")
        scenarios_dir: e.g. Path("scenarios") — used to load metadata.json
            for fixture-citation checks.

    Returns:
        dict mapping scenario_id → ScoreResult.
    """
    from pathlib import Path
    intermediates_dir = Path(intermediates_dir)
    scenarios_dir = Path(scenarios_dir)
    results: dict[str, ScoreResult] = {}
    for sid in sorted(RUBRICS.keys()):
        smoke_path = intermediates_dir / sid / "smoke_test.json"
        if not smoke_path.exists():
            results[sid] = ScoreResult(
                scenario_id=sid, overall_passed=False,
                checks=[CheckResult(
                    name="smoke_test_present", passed=False,
                    message=f"intermediates/{sid}/smoke_test.json missing",
                )],
            )
            continue
        recommendation = json.loads(smoke_path.read_text())
        meta_path = scenarios_dir / sid / "metadata.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
        results[sid] = score_recommendation(sid, recommendation, meta)
    return results
