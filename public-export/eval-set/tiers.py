"""Tier check logic for the cloud-governance eval.

This file is the source of truth for what Floor, Mid, and Rich mean. Each
tier takes a prediction dict and an expectations dict, runs its checks, and
returns a TierResult.

Per-scenario values (allowed lists, keyword groups, fixture names) live in
expectations/NN/evaluation_expectations.json. The Python here applies the
same checks to every scenario.

No LLM calls. No network. Same prediction + same expectations = same result.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class TierResult:
    tier: str               # "floor", "mid", or "rich"
    passed: bool            # all checks in this tier passed
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message,
                 "detail": c.detail}
                for c in self.checks
            ],
        }


# ============================================================
# Floor — does the prediction look like a governance recommendation?
# ============================================================
def score_floor(prediction: dict, expectations: dict) -> TierResult:
    """Floor checks: prediction is shaped right and the categories are in range.

    Any reasonable agent should pass Floor 18/18. A stub baseline should not.
    """
    checks: list[CheckResult] = []

    # finding_type must be in the allowed list
    if "finding_type_allowed" in expectations:
        allowed = expectations["finding_type_allowed"]
        actual = prediction.get("finding_type")
        checks.append(CheckResult(
            name="finding_type",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # primary_tier must be in the allowed list
    if "primary_tier_allowed" in expectations:
        allowed = expectations["primary_tier_allowed"]
        actual = prediction.get("primary_tier")
        checks.append(CheckResult(
            name="primary_tier",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # action_category must be in the allowed list
    if "action_category_allowed" in expectations:
        allowed = expectations["action_category_allowed"]
        actual = prediction.get("action_category")
        checks.append(CheckResult(
            name="action_category",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # specific_change is non-empty (Floor competency: the agent wrote something)
    spec = prediction.get("specific_change") or ""
    checks.append(CheckResult(
        name="specific_change_present",
        passed=len(spec.strip()) >= 20,
        message=f"specific_change length: {len(spec.strip())} chars",
        detail={"min_chars": 20},
    ))

    overall = all(c.passed for c in checks)
    return TierResult(tier="floor", passed=overall, checks=checks)


# ============================================================
# Mid — does the recommendation engage with the right evidence?
# ============================================================
def score_mid(prediction: dict, expectations: dict) -> TierResult:
    """Mid checks: action keywords matched + multi-tier reasoning where needed.

    A careful single-shot agent that reads the telemetry can pass Mid. A
    generic agent that guesses from scenario titles will not.
    """
    checks: list[CheckResult] = []
    text = _prediction_text(prediction)

    # secondary_tier (optional Floor field, but checked at Mid for cross-tier)
    if "secondary_tier_allowed" in expectations:
        allowed = expectations["secondary_tier_allowed"]
        actual = prediction.get("secondary_tier")
        checks.append(CheckResult(
            name="secondary_tier",
            passed=actual in allowed,
            message=f"got {actual!r}, allowed {allowed!r}",
            detail={"allowed": allowed, "produced": actual},
        ))

    # action_keyword_groups: at least min_match groups must hit
    if "action_keyword_groups" in expectations:
        groups = expectations["action_keyword_groups"]
        min_match = expectations.get("action_keyword_min_match", len(groups))
        matched_idx = []
        for i, group in enumerate(groups):
            if any(kw.lower() in text for kw in group):
                matched_idx.append(i)
        passed = len(matched_idx) >= min_match
        checks.append(CheckResult(
            name="action_keywords",
            passed=passed,
            message=(
                f"matched {len(matched_idx)}/{len(groups)} keyword groups "
                f"(need {min_match})"
            ),
            detail={
                "groups": groups,
                "matched_group_indices": matched_idx,
                "min_match": min_match,
            },
        ))

    # multi_tier_evidence: required tier names must appear in the text
    if "multi_tier_evidence" in expectations:
        mt = expectations["multi_tier_evidence"]
        required = mt["must_cite_tiers"]
        min_tiers = mt.get("min_tiers", len(required))
        mentioned = [t for t in required if t in text]
        passed = len(mentioned) >= min_tiers
        checks.append(CheckResult(
            name="multi_tier_evidence",
            passed=passed,
            message=f"mentioned tiers: {mentioned} of {required} (need ≥{min_tiers})",
            detail={
                "required_tiers": required,
                "mentioned_tiers": mentioned,
                "min_tiers": min_tiers,
            },
        ))

    overall = all(c.passed for c in checks) if checks else True
    return TierResult(tier="mid", passed=overall, checks=checks)


# ============================================================
# Rich — does the recommendation show orchestrated synthesis?
# ============================================================
def score_rich(prediction: dict, expectations: dict,
               scenario_metadata: dict | None = None) -> TierResult:
    """Rich checks: cite named fixtures + show quantification.

    Single-shot agents that do not read fixtures fail Rich. Orchestrated
    agents that route subtasks across specialized agents pass.
    """
    checks: list[CheckResult] = []
    text = _prediction_text(prediction)

    # fixture_citation: must cite at least one identifier from a named fixture
    if "must_cite_fixture" in expectations and scenario_metadata is not None:
        fixture_name = expectations["must_cite_fixture"]
        evidence = scenario_metadata.get("scenario_specific_evidence", {}) or {}
        items = evidence.get(fixture_name, []) or []
        identifiers = _extract_fixture_identifiers(fixture_name, items)
        if not identifiers:
            # Fixture is empty in the metadata — not the agent's fault
            checks.append(CheckResult(
                name="fixture_citation",
                passed=True,
                message=f"skipped — {fixture_name} is empty in metadata",
            ))
        else:
            cited = [i for i in identifiers if i.lower() in text]
            checks.append(CheckResult(
                name="fixture_citation",
                passed=len(cited) >= 1,
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

    # Quantification checks only apply when the agent proposes a concrete
    # change. For "no action" framings (no_issue_found, diagnostic_deferral,
    # sla_review) there is no cost projection or state projection to make.
    finding_type = prediction.get("finding_type")
    action_cat = prediction.get("action_category")
    quantification_applies = not (
        finding_type in ("no_issue_found", "diagnostic_deferral")
        or action_cat in ("sla_review", None)
    )

    # cost_impact_quantified: cost_impact section must include a dollar number
    cost_impact = prediction.get("cost_impact") or {}
    has_cost_number = False
    if isinstance(cost_impact, dict):
        for k in ("savings_monthly_usd", "current_monthly_usd",
                  "projected_monthly_usd", "savings_pct"):
            v = cost_impact.get(k)
            if isinstance(v, (int, float)) and v != 0:
                has_cost_number = True
                break
    if quantification_applies:
        checks.append(CheckResult(
            name="cost_impact_quantified",
            passed=has_cost_number,
            message=f"cost_impact has numeric fields: {has_cost_number}",
            detail={"cost_impact": cost_impact},
        ))
    else:
        checks.append(CheckResult(
            name="cost_impact_quantified",
            passed=True,
            message=f"skipped — does not apply to {finding_type}/{action_cat}",
        ))

    # projected_state_quantified: at least one numeric projection field
    proj = prediction.get("projected_state") or {}
    has_proj_number = False
    if isinstance(proj, dict):
        for k, v in proj.items():
            if isinstance(v, (int, float)):
                has_proj_number = True
                break
    if quantification_applies:
        checks.append(CheckResult(
            name="projected_state_quantified",
            passed=has_proj_number,
            message=f"projected_state has numeric fields: {has_proj_number}",
            detail={"projected_state": proj},
        ))
    else:
        checks.append(CheckResult(
            name="projected_state_quantified",
            passed=True,
            message=f"skipped — does not apply to {finding_type}/{action_cat}",
        ))

    # evidence_structured: evidence section has at least one bullet
    # across the three evidence categories
    ev = prediction.get("evidence") or {}
    n_bullets = 0
    if isinstance(ev, dict):
        for cat in ("telemetry_observations", "infrastructure_context",
                    "correlation_observations"):
            bullets = ev.get(cat) or []
            if isinstance(bullets, list):
                n_bullets += len(bullets)
    checks.append(CheckResult(
        name="evidence_structured",
        passed=n_bullets >= 3,
        message=f"evidence bullets total: {n_bullets} (need ≥3)",
        detail={"bullets": n_bullets},
    ))

    overall = all(c.passed for c in checks)
    return TierResult(tier="rich", passed=overall, checks=checks)


# ============================================================
# Helpers
# ============================================================
def _prediction_text(prediction: dict) -> str:
    """Concatenate prediction prose fields into one lowercase string.

    Used by keyword and tier-name checks.
    """
    parts = [
        prediction.get("specific_change") or "",
        prediction.get("reasoning") or "",
    ]
    ev = prediction.get("evidence") or {}
    if isinstance(ev, dict):
        for cat in ("telemetry_observations", "infrastructure_context",
                    "correlation_observations"):
            bullets = ev.get(cat) or []
            if isinstance(bullets, list):
                for b in bullets:
                    if isinstance(b, str):
                        parts.append(b)
    return " ".join(parts).lower()


def _extract_fixture_identifiers(fixture_name: str, items: list) -> list[str]:
    """Pull identifier strings out of one fixture's entries."""
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            if isinstance(item, str):
                out.append(item)
            continue
        if fixture_name == "top_queries":
            for key in ("name", "shorthand", "query_name", "id"):
                if key in item and isinstance(item[key], str):
                    out.append(item[key])
                    break
        elif fixture_name == "top_cache_keys":
            for key in ("pattern", "key", "name"):
                if key in item and isinstance(item[key], str):
                    out.append(item[key])
                    break
        elif fixture_name == "per_instance_breakdown":
            if "instance_id" in item:
                out.append(item["instance_id"])
    return out


# ============================================================
# All three tiers in one call
# ============================================================
def score_all_tiers(prediction: dict, expectations: dict,
                    scenario_metadata: dict | None = None) -> dict:
    """Run Floor, Mid, and Rich and return a single dict."""
    floor = score_floor(prediction, expectations)
    mid = score_mid(prediction, expectations)
    rich = score_rich(prediction, expectations, scenario_metadata)
    return {
        "floor": floor,
        "mid": mid,
        "rich": rich,
        "all_pass": floor.passed and mid.passed and rich.passed,
    }
