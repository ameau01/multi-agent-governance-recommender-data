"""Internal types used by the pipeline.

These are *internal* models — not part of the consumer-facing contract.
The consumer-facing contract lives in `src/contracts/` (synced from agent project).

ScenarioSpec captures the shape of `docs/internal/scenarios/NN.spec.yaml`.
The other models capture intermediate results passed between pipeline stages.
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict


# ============================================================
# Scenario spec — internal representation of NN.spec.yaml
# ============================================================
class ScenarioSpec(BaseModel):
    """Internal model for `docs/internal/scenarios/NN.spec.yaml`.

    Sub-blocks (narrative, business_context, etc.) are typed as `dict[str, Any]`
    in this skeleton — implementer can flesh out sub-models as the pipeline
    matures. The YAML schema is documented in `docs/internal/scenarios/07.spec.yaml`
    which serves as the canonical example.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: str                                    # "01" through "18"
    scenario_name: str
    scenario_type: str                                  # mapped to ScenarioType enum at metadata-build time

    narrative: dict[str, str]
    business_context: dict[str, Any]
    cost_baseline: dict[str, Any]
    tier_topology: dict[str, Any]

    pass1_metrics: dict[str, Any]
    pass2_correlations: list[dict[str, Any]]

    scenario_specific_evidence: dict[str, Any]
    before_after_evidence: dict[str, Any]
    target_recommendation: dict[str, Any]
    evaluation_properties: dict[str, Any]


# ============================================================
# Pipeline stage results
# ============================================================
class Pass1Output(BaseModel):
    """Wire format for Pass 1 output (also persisted to intermediates/NN/pass1.json).

    Uses capitalized tier names for backward compatibility with prompt scaffolds;
    splitter.py renames to lowercase consumer-facing telemetry filenames.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    pass_: Literal[1] = 1                              # serialized as "pass" via alias
    Compute_Metrics: list[dict[str, Any]]
    Database_Metrics: list[dict[str, Any]]
    Cache_Metrics: list[dict[str, Any]]
    Network_Metrics: list[dict[str, Any]]


class Pass2Output(BaseModel):
    """Wire format for Pass 2 output (also persisted to intermediates/NN/pass2.json)."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    pass_: Literal[2] = 2
    Compute_Metrics: list[dict[str, Any]]
    Database_Metrics: list[dict[str, Any]]
    Cache_Metrics: list[dict[str, Any]]
    Network_Metrics: list[dict[str, Any]]


class ScenarioBuildResult(BaseModel):
    """Result of running the full pipeline against one scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    success: bool
    stages_completed: list[str]                        # e.g. ["pass1", "pass2", "splitter", "metadata", "terraform", "qa"]
    qa_passed: bool
    error: str | None = None
    output_dir: str                                    # "scenarios/NN/"
