"""Per-tier topology entries + the aggregate TierTopology.

Per docs/contract-spec.md §12.3.1 (sub-models of ScenarioMetadata).

Each topology entry is set to None on ScenarioMetadata when the corresponding
tier is absent in the scenario. The producer is responsible for enforcing
the topology-vs-telemetry consistency rule (§12.6).
"""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Compute
# ============================================================
class ComputeTopologyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = True
    instance_class: str                                  # e.g. "t3.large"
    instance_count: int = Field(..., ge=1)
    scaling_policy: Literal["none", "target_tracking", "step", "scheduled"]
    auto_scaling_min: int | None = None
    auto_scaling_max: int | None = None


# ============================================================
# Database
# ============================================================
class DatabaseTopologyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = True
    instance_class: str                                  # e.g. "db.r6g.large"
    replicas: int = Field(default=1, ge=1)
    storage_gb: int | None = None


# ============================================================
# Cache
# ============================================================
class CacheTopologyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = True
    node_type: str
    node_count: int = Field(..., ge=1)
    ttl_seconds: int | None = None


# ============================================================
# Network (load balancer)
# ============================================================
class NetworkTopologyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = True
    load_balancer_type: Literal["application", "network"]
    algorithm: Literal["round_robin", "least_outstanding_requests", "ip_hash"]


# ============================================================
# Aggregate
# ============================================================
class TierTopology(BaseModel):
    """All four tiers; None means the scenario does not use that tier."""

    model_config = ConfigDict(extra="forbid")

    compute: ComputeTopologyEntry | None = None
    database: DatabaseTopologyEntry | None = None
    cache: CacheTopologyEntry | None = None
    network: NetworkTopologyEntry | None = None
