"""Shared data contract — Pydantic models + enums + version.

Public API re-exports for convenient import:
    from contracts import ScenarioMetadata, CONTRACT_VERSION
    from contracts import ComputeRecord, DatabaseRecord, CacheRecord, NetworkRecord
    from contracts import TierName, ScenarioType, ActionCategory

Full spec: docs/contract-spec.md
"""

# Version
from contracts.version import CONTRACT_VERSION

# Enums
from contracts.enums import (
    ActionCategory,
    CacheMetric,
    ComputeMetric,
    DatabaseMetric,
    NetworkMetric,
    ScenarioType,
    TierName,
)

# Telemetry records
from contracts.telemetry import (
    CacheRecord,
    ComputeRecord,
    DatabaseRecord,
    NetworkRecord,
)

# Evidence
from contracts.evidence import (
    BeforeAfterEvidence,
    CorrelationPair,
    InstanceBreakdown,
    TopCacheKey,
    TopQuery,
)

# Configurations
from contracts.configurations import (
    CacheTopologyEntry,
    ComputeTopologyEntry,
    DatabaseTopologyEntry,
    NetworkTopologyEntry,
    TierTopology,
)

# Recommendation
from contracts.recommendation import EvaluationProperties, TargetRecommendation

# Narrative
from contracts.narrative import (
    BusinessContext,
    CostBaseline,
    ScenarioNarrative,
    ScenarioSpecificEvidence,
    TelemetryFilePointers,
)

# Top-level metadata
from contracts.metadata import ScenarioMetadata

__all__ = [
    "CONTRACT_VERSION",
    # Enums
    "ActionCategory",
    "CacheMetric",
    "ComputeMetric",
    "DatabaseMetric",
    "NetworkMetric",
    "ScenarioType",
    "TierName",
    # Telemetry
    "CacheRecord",
    "ComputeRecord",
    "DatabaseRecord",
    "NetworkRecord",
    # Evidence
    "BeforeAfterEvidence",
    "CorrelationPair",
    "InstanceBreakdown",
    "TopCacheKey",
    "TopQuery",
    # Configurations
    "CacheTopologyEntry",
    "ComputeTopologyEntry",
    "DatabaseTopologyEntry",
    "NetworkTopologyEntry",
    "TierTopology",
    # Recommendation
    "EvaluationProperties",
    "TargetRecommendation",
    # Narrative
    "BusinessContext",
    "CostBaseline",
    "ScenarioNarrative",
    "ScenarioSpecificEvidence",
    "TelemetryFilePointers",
    # Top-level
    "ScenarioMetadata",
]
