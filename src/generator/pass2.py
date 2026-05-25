"""Pass 2 generator — surgical cross-tier correlation injection.

Takes Pass 1 output and modifies it according to scenario.pass2_correlations,
preserving every Pass 1 signal exactly outside the correlation windows.
Emits the modified telemetry AND the precomputed correlation_evidence.json.

See `docs/internal/generation-methodology.md` §3 for the full Pass 2 contract.
See `prompts/pass2.txt` for the LLM prompt scaffold.
"""

from __future__ import annotations
from pathlib import Path

from generator.types import ScenarioSpec, Pass1Output, Pass2Output
# from contracts.evidence import CorrelationPair   # uncomment after Phase A.1


def generate_pass2(
    spec: ScenarioSpec,
    pass1_output: Pass1Output,
) -> tuple[Pass2Output, list["CorrelationPair"]]:  # type: ignore[name-defined]
    """Run Pass 2 for one scenario.

    Pass-through case: if spec.pass2_correlations is empty, copy Pass 1 to Pass 2
    with `pass` field updated; return ([], no LLM call).

    Correlation case:
      1. Build substitutions from spec.pass2_correlations + Pass 1 JSON.
      2. Call LLM via LLMClient with prompts/pass2.txt.
      3. Parse response as JSON.
      4. Enforce the Pass 2 invariance contract (see _enforce_invariance below).
      5. Compute CorrelationPair records programmatically from the Pass 2 telemetry
         (Pearson coefficient, lag, alignment score per scenario rule).
      6. Return (Pass2Output, list of CorrelationPairs).

    Args:
        spec: Loaded scenario spec.
        pass1_output: The output of the Pass 1 stage.

    Returns:
        (Pass2Output, list of CorrelationPair) — the latter populates
        correlation_evidence.json.

    Raises:
        RuntimeError: if Pass 2 violates the invariance contract.
    """
    raise NotImplementedError("Phase B.3 — see BUILD_PLAN.md §B.3")


def _enforce_invariance(
    spec: ScenarioSpec,
    pass1: Pass1Output,
    pass2: Pass2Output,
) -> None:
    """Verify Pass 2 preserved Pass 1 exactly outside the correlation windows.

    Per generation-methodology.md §3 "Pass 2 contract":
      1. Tiers not in any correlation.effect → arrays match Pass 1 bit-exact.
      2. Tiers that ARE effect targets, in records where no trigger condition
         is satisfied → records match Pass 1 exactly (timestamp + every field).
      3. Timestamps are never modified.

    Raises:
        AssertionError: with a detailed diagnostic on any violation.
    """
    raise NotImplementedError("Phase B.3 — see BUILD_PLAN.md §B.3")


def _compute_correlation_evidence(
    spec: ScenarioSpec,
    pass2_output: Pass2Output,
) -> list["CorrelationPair"]:  # type: ignore[name-defined]
    """Compute Pearson coefficient + lag + alignment score per correlation rule.

    For each rule in spec.pass2_correlations:
      - Extract the trigger metric and effect metric time series.
      - Compute Pearson coefficient across the full 14-day window.
      - Determine lag (0 minutes for "same window", computed for lagged rules).
      - Compute alignment_score: proportion of intervals where both z-scores
        moved in the same direction.

    Returns:
        List of CorrelationPair records, ready to write to correlation_evidence.json.
    """
    raise NotImplementedError("Phase B.3 — see BUILD_PLAN.md §B.3")


def write_pass2_intermediate(output: Pass2Output, intermediates_dir: Path) -> Path:
    """Persist Pass 2 output to `intermediates/NN/pass2.json` for debugging."""
    raise NotImplementedError("Phase B.3")
