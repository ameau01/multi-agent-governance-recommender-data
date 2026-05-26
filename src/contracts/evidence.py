"""Scenario-specific evidence and cross-tier correlation evidence models.

Per docs/contract-spec.md §12.3.1 (ScenarioSpecificEvidence sub-models)
and §12.3.6 (CorrelationPair).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import TierName


# ============================================================
# Top-queries fixture (Scenarios 4, 8)
# ============================================================
class TopQuery(BaseModel):
    """A frequently-executed slow query, used by data-layer recommendations.

    Per generation-conventions.md §3: `count` is the total executions observed
    over the 14-day data window (not a rate).
    """

    model_config = ConfigDict(extra="forbid")

    query_text: str
    count: int = Field(..., ge=1)
    p95_latency_ms: float = Field(..., ge=0)


# ============================================================
# Top-cache-keys fixture (Scenario 7)
# ============================================================
class TopCacheKey(BaseModel):
    """A frequently-accessed cache key pattern.

    Per generation-conventions.md §3: hit/miss counts are totals over the
    14-day window.
    """

    model_config = ConfigDict(extra="forbid")

    key_pattern: str
    hit_count: int = Field(..., ge=0)
    miss_count: int = Field(..., ge=0)


# ============================================================
# Per-instance breakdown (Scenario 5)
# ============================================================
class InstanceBreakdown(BaseModel):
    """Per-instance CPU band, used by load-balancer scenarios.

    `cpu_band` is a free-form description like "78-88% sustained (hot)".
    """

    model_config = ConfigDict(extra="forbid")

    instance_id: str
    cpu_band: str


# ============================================================
# Before/after evidence
# ============================================================
class BeforeAfterEvidence(BaseModel):
    """Reference evidence grounding the target recommendation.

    A "we tried this elsewhere and got this outcome" anchor. Per
    docs/contract-spec.md §12.3.1.
    """

    model_config = ConfigDict(extra="forbid")

    config_before: str
    config_after: str
    observed_outcome_summary: str
    source_attribution: str


# ============================================================
# Cross-tier correlation pair
# ============================================================
class CorrelationPair(BaseModel):
    """One correlated metric pair across two tiers.

    Stored in correlation_evidence.json. Per docs/contract-spec.md §12.3.6.
    """

    model_config = ConfigDict(extra="forbid")

    tier_a: TierName
    tier_b: TierName
    metric_a: str
    metric_b: str
    coefficient: float = Field(..., ge=-1.0, le=1.0)
    lag_minutes: int                                  # 0 = same window; positive = b lags a
    alignment_score: float = Field(..., ge=0, le=1.0)
    description: str
