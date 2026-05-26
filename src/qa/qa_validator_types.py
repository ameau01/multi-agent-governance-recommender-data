"""QA report types — split from qa_validator.py to avoid circular imports."""

from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str
    result: Literal["pass", "fail"]
    message: str | None = None
    details: dict | None = None


class QALayerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checks_run: int
    checks_passed: int
    checks_failed: int
    details: list[CheckResult]


class QAReport(BaseModel):
    """Final QA report for one scenario.

    Persisted to intermediates/NN/qa_report.json per
    docs/internal/generation-qa.md §4.
    """

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    ran_at: str                                # ISO-8601 UTC
    contract_layer: QALayerReport
    semantic_layer: QALayerReport
    overall: Literal["pass", "fail"]
    committed_to_scenarios: bool
