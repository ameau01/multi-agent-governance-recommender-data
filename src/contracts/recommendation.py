"""Target recommendation and evaluation properties.

Per docs/contract-spec.md §12.3.1 (sub-models of ScenarioMetadata).
"""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts.enums import ActionCategory, TierName


class TargetRecommendation(BaseModel):
    """The known correct recommendation for one scenario.

    Used by the agent project's R1–R5 evaluation rubric to score the
    multi-agent system's output. Per docs/contract-spec.md §12.3.1.
    """

    model_config = ConfigDict(extra="forbid")

    finding_type: Literal[
        "issue_found",
        "no_issue_found",
        "insufficient_data",
        "diagnostic_deferral",
    ]
    primary_tier: TierName | None = None
    secondary_tier: TierName | None = None
    action_category: ActionCategory | None = None
    specific_change: str                                 # human-readable
    expected_cost_delta_usd: float                       # negative = savings
    expected_performance_impact: str
    expected_reliability_impact: str
    confidence_expected: Literal["high", "medium", "low"]
    eval_rubric_focus: list[str]                         # e.g. ["R1", "R3"]


class EvaluationProperties(BaseModel):
    """Which evaluation properties this scenario exercises.

    Per docs/contract-spec.md §12.3.1.
    """

    model_config = ConfigDict(extra="forbid")

    exercises_restraint: bool
    exercises_diagnostic_deferral: bool
    exercises_cross_tier_synthesis: bool
    primary_specialist_under_test: Literal[
        "compute_analyst",
        "data_layer_analyst",
        "network_analyst",
        "cross_tier_evaluator",
        "supervisor",
    ]
