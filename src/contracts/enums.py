"""Shared enums for the data contract.

Defined verbatim per docs/contract-spec.md §12.4. These enums are the
canonical vocabulary across the producer (data-gen pipeline) and the
consumer (agent project).

All enums inherit from str so they serialize cleanly to JSON.
"""

from __future__ import annotations
from enum import Enum


class TierName(str, Enum):
    COMPUTE = "compute"
    DATABASE = "database"
    CACHE = "cache"
    NETWORK = "network"


class ScenarioType(str, Enum):
    SINGLE_TIER_NEGATIVE = "single_tier_negative"
    SINGLE_TIER_MILD_NEGATIVE = "single_tier_mild_negative"
    CROSS_TIER_NEGATIVE = "cross_tier_negative"
    MIXED = "mixed"
    HEALTHY = "healthy"
    MOSTLY_HEALTHY = "mostly_healthy"
    DIAGNOSTIC_DEFERRAL = "diagnostic_deferral"


class ActionCategory(str, Enum):
    RIGHTSIZING = "rightsizing"
    REPLICA_ADJUSTMENT = "replica_adjustment"
    POOL_SIZING = "pool_sizing"
    SCALING_POLICY_CHANGE = "scaling_policy_change"
    LOAD_BALANCER_RECONFIGURATION = "load_balancer_reconfiguration"
    QUERY_CACHE_OPTIMIZATION = "query_cache_optimization"
    NETWORK_TOPOLOGY_CHANGE = "network_topology_change"
    SLA_REVIEW = "sla_review"


class ComputeMetric(str, Enum):
    CPU_P50 = "cpu_p50"
    CPU_P95 = "cpu_p95"
    MEMORY_P95 = "memory_p95"
    NETWORK_IN_P95 = "network_in_p95"
    NETWORK_OUT_P95 = "network_out_p95"
    APPLICATION_LATENCY_P95 = "application_p95_latency_ms"


class DatabaseMetric(str, Enum):
    QUERY_P95_LATENCY = "db_query_p95_latency_ms"
    CONNECTIONS_P50 = "db_connections_p50"
    CONNECTIONS_P95 = "db_connections_p95"
    CACHE_HIT_RATIO = "db_cache_hit_ratio"
    IO_WAIT_P95 = "db_io_wait_p95"


class CacheMetric(str, Enum):
    HIT_RATIO = "cache_hit_ratio"
    EVICTIONS_PER_SEC = "cache_evictions_per_sec"
    MEMORY_USED_PCT = "cache_memory_used_pct"
    CONNECTIONS = "cache_connections"


class NetworkMetric(str, Enum):
    LATENCY_P95 = "network_p95_latency_ms"
    ERROR_RATE = "network_error_rate"
    THROUGHPUT_P95 = "network_throughput_p95"
