"""Scenario-quality smoke test — single-LLM-call solvability check.

For each scenario, bundles the scenario folder into a prompt and asks a single
Sonnet call to produce a TargetRecommendation. Compares the LLM's recommendation
against the spec's target on four fields (finding_type, primary_tier, action_category,
specific_change). Threshold for the aggregate: GREEN ≥14, YELLOW 12-13, RED ≤11.

See `docs/internal/scenario-quality-smoke-test.md` for the full design.
"""

from __future__ import annotations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from generator.types import ScenarioSpec


# ============================================================
# Smoke test result types
# ============================================================
class FieldComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str | None
    produced: str | None
    match: bool


class SmokeTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    outcome: Literal["pass", "partial", "fail"]
    finding_type: FieldComparison
    primary_tier: FieldComparison
    action_category: FieldComparison
    specific_change: FieldComparison


class SmokeTestReport(BaseModel):
    """Aggregate smoke-test report across all scenarios.

    Persisted to intermediates/smoke_test_report.json per
    docs/internal/scenario-quality-smoke-test.md §4.
    """

    model_config = ConfigDict(extra="forbid")
    ran_at: str                                # ISO-8601 UTC
    scenarios_tested: int
    passed: int
    partial: int
    failed: int
    aggregate_status: Literal["green", "yellow", "red"]
    details: list[SmokeTestResult]


# ============================================================
# Entry points
# ============================================================
def smoke_test_scenario(
    scenario_id: str,
    scenarios_dir: Path,
    spec: ScenarioSpec,
) -> SmokeTestResult:
    """Run the smoke test for one scenario.

    Steps (see scenario-quality-smoke-test.md §2):
      1. Build the LLM prompt:
         - metadata.json *minus* target_recommendation and evaluation_properties
         - per-tier telemetry summaries (p50/p95/mean/min/max/stddev + daily averages
           + business-hours-vs-off-hours split) — NOT raw 1,344 records
         - correlation_evidence.json
         - main.tf
      2. Call Sonnet with the bundled prompt, ask for TargetRecommendation JSON.
      3. Compare against spec.target_recommendation on four fields.
         - finding_type / primary_tier / action_category: exact match
         - specific_change: one-line Haiku LLM-as-judge ("substantively the same change?")
      4. Score: pass = 4/4, partial = 2-3/4, fail = 0-1/4.

    Returns:
        SmokeTestResult with per-field comparison.
    """
    raise NotImplementedError("Phase B.5.5 / C.2.5 — see BUILD_PLAN.md §B.5.5")


def smoke_test_all(scenarios_dir: Path) -> SmokeTestReport:
    """Run the smoke test across all 18 scenarios.

    Aggregates into a SmokeTestReport with the green/yellow/red verdict.
    """
    raise NotImplementedError("Phase C.2.5 — see BUILD_PLAN.md §C.2.5")


# ============================================================
# Prompt-building helpers
# ============================================================
def _build_smoke_test_prompt(scenario_dir: Path) -> str:
    """Bundle metadata (minus target), telemetry summaries, correlations, and Terraform.

    Strip target_recommendation and evaluation_properties from metadata before
    inclusion — these are the ground truth and would leak the answer.
    """
    raise NotImplementedError("Phase B.5.5")


def _summarize_telemetry(telemetry_records: list) -> dict:
    """Reduce 1,344 records to a compact summary for prompt injection.

    Per scenario-quality-smoke-test.md §2.1:
      - p50, p95, mean, min, max, stddev across the full window
      - daily averages (14 entries)
      - business-hours-vs-off-hours split where relevant
    """
    raise NotImplementedError("Phase B.5.5")


def _judge_specific_change(target: str, produced: str) -> bool:
    """One-line Haiku LLM-as-judge: "substantively the same change? YES/NO" """
    raise NotImplementedError("Phase B.5.5")
