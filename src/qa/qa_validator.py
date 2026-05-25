"""QA validator — runs contract + semantic checks against a generated scenario folder.

Two layers:

    Contract layer (defense in depth): every check from `docs/contract-spec.md` §12.6.
      • Pydantic schema validation on every file
      • Contract version match
      • Record count == 1344 per non-empty tier
      • Timestamp continuity (15-min, monotonic, UTC)
      • Cross-tier alignment
      • Topology-vs-telemetry consistency
      • Scenario-specific evidence presence rules
      • Terraform parseability

    Semantic layer (the data-gen-specific value-add):
      • 3.1 Healthy-band check (healthy tiers stay in band ≥13 of 14 days)
      • 3.2 Pattern-frequency check (11-of-14 or 10-of-10 weekday rule)
      • 3.3 Weekend behavior check (40–60% production / 10–25% internal)
      • 3.4 Pass 2 invariance check (compare against intermediates/NN/pass1.json)
      • 3.5 Correlation timing check
      • 3.6 Correlation magnitude check
      • 3.7 No-spurious-correlation check
      • 3.8 SLA description derivation check
      • 3.9 Cost baseline sum invariant
      • 3.10 Per-instance breakdown consistency (Scenario 5 only)

See `docs/internal/generation-qa.md` for the full rules.
"""

from __future__ import annotations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from generator.types import ScenarioSpec


# ============================================================
# QA report types
# ============================================================
class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str                                # e.g. "correlation_magnitude"
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

    Persisted to intermediates/NN/qa_report.json per generation-qa.md §4.
    """

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    ran_at: str                                # ISO-8601 UTC
    contract_layer: QALayerReport
    semantic_layer: QALayerReport
    overall: Literal["pass", "fail"]
    committed_to_scenarios: bool


# ============================================================
# Validator entry point
# ============================================================
def validate_scenario(
    scenario_id: str,
    scenarios_dir: Path,
    spec: ScenarioSpec,
    intermediates_dir: Path,
) -> QAReport:
    """Run both layers and emit a QAReport.

    Args:
        scenario_id: e.g. "07".
        scenarios_dir: Root scenarios/ directory containing scenarios/NN/.
        spec: Loaded scenario spec for the semantic checks.
        intermediates_dir: Where intermediates/NN/pass1.json lives (for Pass 2 invariance check).

    Returns:
        QAReport with per-check details and overall pass/fail.
    """
    raise NotImplementedError("Phase B.5 — see BUILD_PLAN.md §B.5")


# ============================================================
# Contract layer (defense in depth — mirrors agent's Input Harness)
# ============================================================
def _run_contract_checks(scenario_dir: Path) -> QALayerReport:
    """All checks from contract-spec.md §12.6. Raises nothing; returns the report."""
    raise NotImplementedError("Phase B.5")


# ============================================================
# Semantic layer (each check is its own function for readability)
# ============================================================
def _check_healthy_band(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Healthy tiers stay inside healthy-baselines.md ranges on ≥13 of 14 days."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.1")


def _check_pattern_frequency(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Declared patterns hold on ≥11 of 14 days (or all 10 weekday dates)."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.2")


def _check_weekend_behavior(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Weekend averages match the tier-1/2/3 conventions."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.3")


def _check_pass2_invariance(
    scenario_dir: Path, spec: ScenarioSpec, intermediates_dir: Path
) -> CheckResult:
    """Pass 2 preserved Pass 1 exactly outside the correlation windows."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.4")


def _check_correlation_timing(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Correlation effects appear within the spec'd timing windows of triggers."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.5")


def _check_correlation_magnitude(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Adjusted values fall within (Pass 1 baseline + adjustment) ± 15%."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.6")


def _check_no_spurious_correlation(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Tier pairs not declared correlated have |Pearson| < 0.30."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.7")


def _check_sla_description_derivation(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """metadata.json.sla_target_description matches the derivation formula."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.8")


def _check_cost_baseline_sum(scenario_dir: Path) -> CheckResult:
    """monthly_cost_total_usd == sum(by_tier.values())."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.9")


def _check_per_instance_consistency(scenario_dir: Path, spec: ScenarioSpec) -> CheckResult:
    """Scenario 5 only: per_instance_breakdown matches per-instance telemetry."""
    raise NotImplementedError("Phase B.5 — generation-qa.md §3.10")


def _run_semantic_checks(
    scenario_dir: Path,
    spec: ScenarioSpec,
    intermediates_dir: Path,
) -> QALayerReport:
    """Run all 10 semantic checks and aggregate into a QALayerReport."""
    raise NotImplementedError("Phase B.5")
