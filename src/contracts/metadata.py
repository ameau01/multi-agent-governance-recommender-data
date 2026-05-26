"""Top-level ScenarioMetadata — the contract for metadata.json.

Per docs/contract-spec.md §12.3.1.
"""

from __future__ import annotations
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from contracts.configurations import TierTopology
from contracts.enums import ScenarioType
from contracts.evidence import BeforeAfterEvidence
from contracts.narrative import (
    BusinessContext,
    CostBaseline,
    ScenarioNarrative,
    ScenarioSpecificEvidence,
    TelemetryFilePointers,
)
from contracts.recommendation import EvaluationProperties, TargetRecommendation


class ScenarioMetadata(BaseModel):
    """Top-level metadata.json shape.

    The data-gen pipeline writes this file per scenario. The agent project's
    Data Service reads it and exposes derived views via its read-method
    surface. Per docs/contract-spec.md §12.3.1.
    """

    model_config = ConfigDict(extra="forbid")

    # === Identity ===
    contract_version: str
    scenario_id: str                                  # "01" through "18"
    scenario_name: str
    scenario_type: ScenarioType
    generated_at: datetime

    # === Narrative — for human browsing ===
    narrative: ScenarioNarrative

    # === Business context ===
    business_context: BusinessContext

    # === Cost ===
    cost_baseline: CostBaseline

    # === Tier topology ===
    tier_topology: TierTopology

    # === Scenario-specific evidence pointers (always present, may be empty) ===
    scenario_specific_evidence: ScenarioSpecificEvidence

    # === Before/after evidence for recommendation grounding ===
    before_after_evidence: BeforeAfterEvidence

    # === Target recommendation for eval comparison ===
    target_recommendation: TargetRecommendation

    # === Evaluation properties ===
    evaluation_properties: EvaluationProperties

    # === File pointers (always the same names, but recorded for completeness) ===
    telemetry_file_pointers: TelemetryFilePointers
    infrastructure_file: str                          # always "main.tf"
