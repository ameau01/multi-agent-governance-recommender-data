"""Narrative + business-context + cost + scenario-specific evidence wrappers.

Per docs/contract-spec.md §12.3.1.
"""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import TierName
from contracts.evidence import InstanceBreakdown, TopCacheKey, TopQuery


# ============================================================
# ScenarioNarrative — the four-paragraph human-facing description
# ============================================================
class ScenarioNarrative(BaseModel):
    """Human-readable description of what each scenario is about.

    Per docs/contract-spec.md §12.3.1 (sub-model of ScenarioMetadata).
    """

    model_config = ConfigDict(extra="forbid")

    what_this_demonstrates: str
    why_this_scenario_exists: str
    what_the_agent_should_conclude: str
    what_distinguishes_good_from_great: str


# ============================================================
# BusinessContext — application criticality, SLA, etc.
# ============================================================
class BusinessContext(BaseModel):
    """Application criticality, SLA target, description.

    `sla_target_description` is derived from the structured fields per
    generation-conventions.md §6.
    """

    model_config = ConfigDict(extra="forbid")

    description: str
    sla_target_description: str                       # human-readable
    sla_target_p95_ms: int                            # machine-readable
    sla_target_availability_pct: float = Field(..., ge=0, le=100)
    criticality: Literal["tier-1", "tier-2", "tier-3"]


# ============================================================
# CostBaseline — total + per-tier monthly cost
# ============================================================
class CostBaseline(BaseModel):
    """Monthly cost: total + per-tier breakdown.

    by_tier always contains all four tiers; absent tiers get 0.0.
    monthly_cost_total_usd is the sum of by_tier values.
    """

    model_config = ConfigDict(extra="forbid")

    monthly_cost_total_usd: float = Field(..., ge=0)
    by_tier: dict[TierName, float]


# ============================================================
# ScenarioSpecificEvidence — fixtures for query/cache-key/per-instance recs
# ============================================================
class ScenarioSpecificEvidence(BaseModel):
    """Per-scenario evidence fixtures.

    Each list is non-empty only for scenarios where the target recommendation
    references them. Validation rules per docs/contract-spec.md §12.6.
    """

    model_config = ConfigDict(extra="forbid")

    top_queries: list[TopQuery] = []
    top_cache_keys: list[TopCacheKey] = []
    per_instance_breakdown: list[InstanceBreakdown] = []


# ============================================================
# TelemetryFilePointers — recorded for completeness
# ============================================================
class TelemetryFilePointers(BaseModel):
    """Pointers to the four telemetry files.

    Always the same standard names; recorded in metadata for completeness.
    """

    model_config = ConfigDict(extra="forbid")

    compute: str = "compute_telemetry.json"
    database: str = "database_telemetry.json"
    cache: str = "cache_telemetry.json"
    network: str = "network_telemetry.json"
