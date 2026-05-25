"""Scenario-quality smoke test — split into two resumable phases.

The smoke test verifies that each generated scenario is *solvable* — that a
baseline LLM can reach the target recommendation from the data alone. It is
split into two phases so that an interruption to the cheap judge phase does
not waste the more expensive Opus recommendation phase.

# Phase 1: `smoke_test` — Opus recommendation generation

For each scenario, bundle the scenario folder into a prompt and ask Opus 4.6
for a `TargetRecommendation` shaped result. Save to
`intermediates/NN/smoke_test.json`. Cost: ~$1.45 across all 18 scenarios.

# Phase 2: `smoke_test_judge` — Haiku judging of recommendations

For each scenario, load the saved Opus recommendation, compare against the
spec's target on four fields, use Haiku 4.5 for the one-line "substantively
the same change? YES/NO" judgment on `specific_change`. Save outcome to
`intermediates/NN/smoke_test_judge.json`. Cost: negligible (~$0.01 across all).

# Why split?

- **Recovery cost asymmetry.** Opus ($5/$25 per MTok) is ~5× the cost of
  Sonnet and ~25× the cost of Haiku. If the judge phase is interrupted
  mid-run after Opus has already produced 12 recommendations, we don't want
  to re-pay for those 12 Opus calls just to finish the cheap judging.
- **Manual review.** With the recommendations stored separately on disk,
  you can review Opus's raw outputs in `intermediates/NN/smoke_test.json`
  before letting the judge score them. If a recommendation looks wrong,
  you can fix the scenario spec and regenerate, without spending
  judge tokens on bad data.
- **Independent re-runs.** If you tune the judge prompt or comparison logic,
  you can re-run just the judge phase against unchanged Opus recommendations.

# Resumability

Both phases use the checkpoint pattern in `generator.checkpoint`. If the
process is interrupted at scenario N of phase 1, re-running `smoke_test_all`
will scan `intermediates/*/smoke_test.json`, skip the N-1 completed
scenarios, and continue from N.

See `docs/internal/scenario-quality-smoke-test.md` for the full design.
"""

from __future__ import annotations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from generator.types import ScenarioSpec


# ============================================================
# Result types
# ============================================================
class SmokeTestRecommendation(BaseModel):
    """Opus's output for one scenario, before judging.

    Persisted to `intermediates/NN/smoke_test.json` after Phase 1. Used as
    input to Phase 2 (judging). The shape mirrors the consumer-facing
    `TargetRecommendation` model from the shared contract, so a reviewer
    can diff it against `metadata.json.target_recommendation` by hand.
    """

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    finding_type: Literal["issue_found", "no_issue_found", "insufficient_data", "diagnostic_deferral"]
    primary_tier: Literal["compute", "database", "cache", "network"] | None = None
    secondary_tier: Literal["compute", "database", "cache", "network"] | None = None
    action_category: str | None = None      # ActionCategory enum value, or None
    specific_change: str
    raw_model_response: str | None = None   # full Opus response for audit


class FieldComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str | None
    produced: str | None
    match: bool


class SmokeTestJudgeResult(BaseModel):
    """The judging outcome for one scenario.

    Persisted to `intermediates/NN/smoke_test_judge.json` after Phase 2.
    Combined with the Phase 1 recommendation to form the per-scenario
    smoke-test entry in the aggregate report.
    """

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    outcome: Literal["pass", "partial", "fail"]
    finding_type: FieldComparison
    primary_tier: FieldComparison
    action_category: FieldComparison
    specific_change: FieldComparison


class SmokeTestReport(BaseModel):
    """Aggregate report across all scenarios. Combines Phase 1 + Phase 2.

    Persisted to `intermediates/smoke_test_report.json` after both phases
    complete on all scenarios.
    """

    model_config = ConfigDict(extra="forbid")
    ran_at: str
    scenarios_tested: int
    passed: int
    partial: int
    failed: int
    aggregate_status: Literal["green", "yellow", "red"]
    details: list[SmokeTestJudgeResult]


# ============================================================
# Phase 1: smoke_test — Opus recommendation generation
# ============================================================
def generate_smoke_test_recommendation(
    scenario_id: str,
    scenarios_dir: Path,
) -> SmokeTestRecommendation:
    """Run Phase 1 of the smoke test for one scenario.

    Steps:
      1. Read the scenario folder under scenarios/NN/.
      2. Build the prompt (metadata minus target + telemetry summaries +
         correlation_evidence + main.tf). Strip target_recommendation and
         evaluation_properties — they're the ground truth and would leak.
      3. Call Opus 4.6 (model from constants.SMOKE_TEST_MODEL).
      4. Parse the model response as TargetRecommendation-shaped JSON.
      5. Return SmokeTestRecommendation.

    The caller (smoke_test_all or smoke_test_scenario in cli.py) is
    responsible for writing the result to
    `intermediates/NN/smoke_test.json` via `checkpoint.write_pydantic_atomic`.

    Returns:
        SmokeTestRecommendation containing Opus's structured output.

    Raises:
        FileNotFoundError: if scenarios/NN/ is missing required files.
        ValueError: if the Opus response doesn't parse as expected JSON.
    """
    raise NotImplementedError(
        "Phase B.5.5 — see docs/internal/scenario-quality-smoke-test.md §2.1–2.2"
    )


def generate_smoke_test_recommendations_all(
    scenarios_dir: Path,
    intermediates_dir: Path,
) -> dict[str, SmokeTestRecommendation]:
    """Run Phase 1 across all scenarios, resumable.

    Uses checkpoint.partition_scenarios to skip already-completed scenarios.
    For each remaining scenario, calls generate_smoke_test_recommendation
    and persists via checkpoint.write_pydantic_atomic.

    Returns:
        dict mapping scenario_id → SmokeTestRecommendation, including both
        previously-completed (loaded from disk) and newly-generated entries.
    """
    raise NotImplementedError(
        "Phase B.5.5 / C.2.5 — reference impl:\n"
        "    from generator.checkpoint import partition_scenarios, write_pydantic_atomic, checkpoint_path\n"
        "    from generator.constants import ALL_SCENARIO_IDS\n"
        "    partition = partition_scenarios(ALL_SCENARIO_IDS, 'smoke_test', intermediates_dir, SmokeTestRecommendation)\n"
        "    print(partition.summary_line())\n"
        "    results = {sid: SmokeTestRecommendation.model_validate(read_json(...)) for sid in partition.completed}\n"
        "    for sid in partition.remaining:\n"
        "        rec = generate_smoke_test_recommendation(sid, scenarios_dir)\n"
        "        write_pydantic_atomic(checkpoint_path(sid, 'smoke_test', intermediates_dir), rec)\n"
        "        results[sid] = rec\n"
        "    return results"
    )


# ============================================================
# Phase 2: smoke_test_judge — Haiku judging of recommendations
# ============================================================
def judge_smoke_test_recommendation(
    scenario_id: str,
    recommendation: SmokeTestRecommendation,
    spec: ScenarioSpec,
) -> SmokeTestJudgeResult:
    """Run Phase 2 (judging) for one scenario.

    Compares the Opus recommendation against the spec's target on four fields:
      - finding_type: exact string match
      - primary_tier: exact string match (None matches None)
      - action_category: exact enum match (None matches None)
      - specific_change: Haiku LLM-as-judge — one-line "substantively the same? YES/NO"

    Scoring:
      - pass: 4/4 fields match
      - partial: 2-3/4
      - fail: 0-1/4

    Args:
        scenario_id: e.g. "07".
        recommendation: The Phase 1 Opus output.
        spec: The scenario spec (for spec.target_recommendation).

    Returns:
        SmokeTestJudgeResult with per-field comparisons and overall outcome.
    """
    raise NotImplementedError(
        "Phase B.5.5 — see docs/internal/scenario-quality-smoke-test.md §2.3–2.4"
    )


def judge_smoke_test_recommendations_all(
    scenarios_dir: Path,
    intermediates_dir: Path,
) -> dict[str, SmokeTestJudgeResult]:
    """Run Phase 2 across all scenarios, resumable.

    Required precondition: Phase 1 (`generate_smoke_test_recommendations_all`)
    has produced `intermediates/*/smoke_test.json` for every scenario the
    judge needs to score. Scenarios without a Phase 1 checkpoint are skipped
    with a warning (run Phase 1 first).

    Resume logic via checkpoint.partition_scenarios on the "smoke_test_judge"
    phase. Re-running picks up only the scenarios whose judge result is
    missing or invalid.

    Returns:
        dict mapping scenario_id → SmokeTestJudgeResult.
    """
    raise NotImplementedError(
        "Phase B.5.5 / C.2.5 — same resumable pattern as "
        "generate_smoke_test_recommendations_all, but reads "
        "smoke_test.json + scenario spec to produce smoke_test_judge.json."
    )


# ============================================================
# Aggregation (after both phases complete)
# ============================================================
def build_smoke_test_report(
    judge_results: dict[str, SmokeTestJudgeResult],
) -> SmokeTestReport:
    """Aggregate per-scenario judge results into a top-level report.

    Threshold (per scenario-quality-smoke-test.md §3):
      - ≥14 pass → GREEN
      - 12–13 pass → YELLOW
      - ≤11 pass → RED
    """
    raise NotImplementedError("Phase B.5.5")


# ============================================================
# Helpers for prompt-building (shared between Phase 1 and Phase 2)
# ============================================================
def _build_recommendation_prompt(scenario_dir: Path) -> str:
    """Bundle metadata (minus target), telemetry summaries, correlations, terraform.

    Strip target_recommendation and evaluation_properties from metadata before
    inclusion — these are the ground truth and would leak the answer.
    """
    raise NotImplementedError("Phase B.5.5")


def _summarize_telemetry(telemetry_records: list) -> dict:
    """Reduce 1,344 records to a compact summary for prompt injection.

    p50, p95, mean, min, max, stddev across the window + daily averages +
    business-hours/off-hours split. Avoid dumping raw records into the prompt.
    """
    raise NotImplementedError("Phase B.5.5")


def _judge_specific_change(target: str, produced: str) -> bool:
    """One-line Haiku LLM-as-judge: "substantively the same change? YES/NO" """
    raise NotImplementedError("Phase B.5.5")
