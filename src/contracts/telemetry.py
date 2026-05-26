"""Per-tier telemetry record models.

Each tier's *_telemetry.json file is a JSON array of records of the
corresponding type. Field shapes per docs/contract-spec.md §12.3.2–12.3.5.

All percentage fields are constrained to 0–100. Ratios (cache hit ratios,
error rates) are constrained to 0–1.
"""

from __future__ import annotations
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Compute tier
# ============================================================
class ComputeRecord(BaseModel):
    """One 15-minute sample of compute-tier telemetry.

    Per docs/contract-spec.md §12.3.2.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    cpu_p50: float = Field(..., ge=0, le=100)
    cpu_p95: float = Field(..., ge=0, le=100)
    memory_p95: float = Field(..., ge=0, le=100)
    network_in_p95: float = Field(..., ge=0)          # Mbps
    network_out_p95: float = Field(..., ge=0)         # Mbps
    application_p95_latency_ms: float = Field(..., ge=0)
    instance_id: str | None = None                    # only for Scenario 5


# ============================================================
# Database tier
# ============================================================
class DatabaseRecord(BaseModel):
    """One 15-minute sample of database-tier telemetry.

    Per docs/contract-spec.md §12.3.3.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    db_query_p95_latency_ms: float = Field(..., ge=0)
    db_connections_p50: int = Field(..., ge=0)
    db_connections_p95: int = Field(..., ge=0)
    db_cache_hit_ratio: float = Field(..., ge=0, le=1)
    db_io_wait_p95: float = Field(..., ge=0, le=100)


# ============================================================
# Cache tier
# ============================================================
class CacheRecord(BaseModel):
    """One 15-minute sample of cache-tier telemetry.

    Per docs/contract-spec.md §12.3.4.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    cache_hit_ratio: float = Field(..., ge=0, le=1)
    cache_evictions_per_sec: float = Field(..., ge=0)
    cache_memory_used_pct: float = Field(..., ge=0, le=100)
    cache_connections: int = Field(..., ge=0)


# ============================================================
# Network tier
# ============================================================
class NetworkRecord(BaseModel):
    """One 15-minute sample of network-tier telemetry.

    Per docs/contract-spec.md §12.3.5.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    network_p95_latency_ms: float = Field(..., ge=0)
    network_error_rate: float = Field(..., ge=0, le=1)
    network_throughput_p95: float = Field(..., ge=0)  # Mbps
