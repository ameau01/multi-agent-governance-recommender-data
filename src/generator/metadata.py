"""Programmatic ScenarioMetadata builder.

Reads a loaded ScenarioSpec and emits a Pydantic-validated metadata.json
into the scenario's output directory. Deterministic — no LLM involvement.

All per-field mappings follow docs/internal/generation-methodology.md §4
and docs/internal/generation-conventions.md §§5–8. The most important
conventions enforced here:

  - tier_topology entries with present=false (or absent) → None
  - cost_baseline.by_tier auto-filled with 0.0 for absent tiers
  - monthly_cost_total_usd auto-computed from by_tier sum
  - sla_target_description derived from structured fields
  - telemetry_file_pointers → standard names
  - infrastructure_file → "main.tf"

These rules guarantee that the SLA description, cost total, and topology
representation are always internally consistent, regardless of what the
spec author wrote.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from contracts import (
    BeforeAfterEvidence,
    BusinessContext,
    CacheTopologyEntry,
    ComputeTopologyEntry,
    CostBaseline,
    DatabaseTopologyEntry,
    EvaluationProperties,
    InstanceBreakdown,
    NetworkTopologyEntry,
    ScenarioMetadata,
    ScenarioNarrative,
    ScenarioSpecificEvidence,
    ScenarioType,
    TargetRecommendation,
    TelemetryFilePointers,
    TierName,
    TierTopology,
    TopCacheKey,
    TopQuery,
)
from contracts.enums import ActionCategory
from contracts.version import CONTRACT_VERSION

from generator.checkpoint import write_pydantic_atomic
from generator.types import ScenarioSpec


# ============================================================
# SLA description derivation (per generation-conventions.md §6)
# ============================================================
def derive_sla_description(p95_ms: int, availability_pct: float) -> str:
    """Canonical SLA description string used in metadata.json.

    Format: "<pct>% availability, P95 < <ms>ms"
    """
    # Use %g to avoid trailing .0 on integer-valued floats
    avail_str = f"{availability_pct:g}"
    return f"{avail_str}% availability, P95 < {p95_ms}ms"


# ============================================================
# Tier topology builders — set to None if not present
# ============================================================
def _build_compute_topology(spec_dict: dict | None) -> ComputeTopologyEntry | None:
    if not spec_dict or not spec_dict.get("present", True):
        return None
    return ComputeTopologyEntry(**spec_dict)


def _build_database_topology(spec_dict: dict | None) -> DatabaseTopologyEntry | None:
    if not spec_dict or not spec_dict.get("present", True):
        return None
    return DatabaseTopologyEntry(**spec_dict)


def _build_cache_topology(spec_dict: dict | None) -> CacheTopologyEntry | None:
    if not spec_dict or not spec_dict.get("present", True):
        return None
    return CacheTopologyEntry(**spec_dict)


def _build_network_topology(spec_dict: dict | None) -> NetworkTopologyEntry | None:
    if not spec_dict or not spec_dict.get("present", True):
        return None
    return NetworkTopologyEntry(**spec_dict)


def _build_tier_topology(spec: ScenarioSpec) -> TierTopology:
    return TierTopology(
        compute=_build_compute_topology(spec.tier_topology.get("compute")),
        database=_build_database_topology(spec.tier_topology.get("database")),
        cache=_build_cache_topology(spec.tier_topology.get("cache")),
        network=_build_network_topology(spec.tier_topology.get("network")),
    )


# ============================================================
# Cost baseline — auto-fill absent tiers, auto-compute total
# ============================================================
def _build_cost_baseline(spec: ScenarioSpec) -> CostBaseline:
    by_tier_raw = spec.cost_baseline.get("by_tier", {}) or {}
    # Coerce string keys to TierName, fill missing tiers with 0.0
    by_tier: dict[TierName, float] = {}
    for tier in TierName:
        by_tier[tier] = float(by_tier_raw.get(tier.value, 0.0))
    total = sum(by_tier.values())
    return CostBaseline(monthly_cost_total_usd=total, by_tier=by_tier)


# ============================================================
# Scenario-specific evidence
# ============================================================
def _build_scenario_specific_evidence(spec: ScenarioSpec) -> ScenarioSpecificEvidence:
    raw = spec.scenario_specific_evidence or {}
    return ScenarioSpecificEvidence(
        top_queries=[TopQuery(**q) for q in raw.get("top_queries", []) or []],
        top_cache_keys=[TopCacheKey(**k) for k in raw.get("top_cache_keys", []) or []],
        per_instance_breakdown=[
            InstanceBreakdown(**b) for b in raw.get("per_instance_breakdown", []) or []
        ],
    )


# ============================================================
# Target recommendation — map string enums + handle None action_category
# ============================================================
def _build_target_recommendation(spec: ScenarioSpec) -> TargetRecommendation:
    raw = dict(spec.target_recommendation)  # shallow copy
    primary_tier = raw.get("primary_tier")
    if isinstance(primary_tier, str):
        raw["primary_tier"] = TierName(primary_tier)
    secondary_tier = raw.get("secondary_tier")
    if isinstance(secondary_tier, str):
        raw["secondary_tier"] = TierName(secondary_tier)
    action_category = raw.get("action_category")
    if isinstance(action_category, str):
        raw["action_category"] = ActionCategory(action_category)
    return TargetRecommendation(**raw)


# ============================================================
# Public API
# ============================================================
def build_metadata(spec: ScenarioSpec) -> ScenarioMetadata:
    """Build a contract-conformant ScenarioMetadata from a ScenarioSpec.

    Args:
        spec: Loaded scenario spec from generator.spec_loader.load_spec.

    Returns:
        ScenarioMetadata, Pydantic-validated on construction.

    Raises:
        pydantic.ValidationError: if the derived metadata is invalid.
        ValueError: if scenario_type doesn't match a ScenarioType enum value.
    """
    # Map scenario_type str → enum
    try:
        scenario_type = ScenarioType(spec.scenario_type)
    except ValueError as e:
        raise ValueError(
            f"Spec {spec.scenario_id}: scenario_type {spec.scenario_type!r} "
            f"is not a valid ScenarioType enum value."
        ) from e

    business_context = BusinessContext(
        description=spec.business_context["description"],
        sla_target_description=derive_sla_description(
            spec.business_context["sla_target_p95_ms"],
            spec.business_context["sla_target_availability_pct"],
        ),
        sla_target_p95_ms=spec.business_context["sla_target_p95_ms"],
        sla_target_availability_pct=spec.business_context["sla_target_availability_pct"],
        criticality=spec.business_context["criticality"],
    )

    return ScenarioMetadata(
        contract_version=CONTRACT_VERSION,
        scenario_id=spec.scenario_id,
        scenario_name=spec.scenario_name,
        scenario_type=scenario_type,
        generated_at=datetime.now(timezone.utc),
        narrative=ScenarioNarrative(**spec.narrative),
        business_context=business_context,
        cost_baseline=_build_cost_baseline(spec),
        tier_topology=_build_tier_topology(spec),
        scenario_specific_evidence=_build_scenario_specific_evidence(spec),
        before_after_evidence=BeforeAfterEvidence(**spec.before_after_evidence),
        target_recommendation=_build_target_recommendation(spec),
        evaluation_properties=EvaluationProperties(**spec.evaluation_properties),
        telemetry_file_pointers=TelemetryFilePointers(),
        infrastructure_file="main.tf",
    )


def write_metadata(metadata: ScenarioMetadata, output_dir: Path) -> Path:
    """Atomically write metadata.json into the scenario's output directory.

    Args:
        metadata: Built ScenarioMetadata.
        output_dir: e.g. scenarios/07/. Created if it doesn't exist.

    Returns:
        Absolute path to the written metadata.json.
    """
    target = output_dir / "metadata.json"
    write_pydantic_atomic(target, metadata)
    return target
