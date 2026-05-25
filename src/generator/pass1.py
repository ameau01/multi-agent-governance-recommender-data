"""Pass 1 generator — base time-series per tier, independent of cross-tier correlations.

Drives an LLM call per scenario to produce 1,344 records per tier (or 1344×N for
Scenario 5's per-instance compute records), validates each record against the
Pydantic contract models on construction, and persists to `intermediates/NN/pass1.json`.

See `docs/internal/generation-methodology.md` §2 for the full Pass 1 contract.
See `prompts/pass1.txt` for the LLM prompt scaffold.
"""

from __future__ import annotations
from pathlib import Path

from generator.types import ScenarioSpec, Pass1Output


def generate_pass1(spec: ScenarioSpec) -> Pass1Output:
    """Run Pass 1 for one scenario.

    Steps:
      1. Build substitutions dict from spec + healthy-baselines.md.
      2. Call the LLM via LLMClient with prompts/pass1.txt.
      3. Parse response as JSON.
      4. Validate each record against the corresponding Pydantic model
         (ComputeRecord, DatabaseRecord, CacheRecord, NetworkRecord).
      5. Assert record count == 1344 per non-empty tier (or N×1344 for Scenario 5).
      6. Assert timestamp continuity (15-min, monotonic, starts at DATA_WINDOW_START_UTC).
      7. Retry up to 3× with diagnostic appended if any check fails.

    Args:
        spec: Loaded scenario spec.

    Returns:
        Pass1Output with the four telemetry arrays (some may be empty []).

    Raises:
        RuntimeError: if all 3 retries fail validation.
    """
    raise NotImplementedError("Phase B.2 — see BUILD_PLAN.md §B.2")


def write_pass1_intermediate(output: Pass1Output, intermediates_dir: Path) -> Path:
    """Persist Pass 1 output to `intermediates/NN/pass1.json` for debugging and Pass 2."""
    raise NotImplementedError("Phase B.2 — see BUILD_PLAN.md §B.2")


def read_pass1_intermediate(scenario_id: str, intermediates_dir: Path) -> Pass1Output:
    """Read a previously-generated Pass 1 output. Used by Pass 2 and by debugging tools."""
    raise NotImplementedError("Phase B.2 — see BUILD_PLAN.md §B.2")


# ============================================================
# Helpers for building substitutions (see generation-methodology.md §2)
# ============================================================
def _format_pass1_metrics_block(spec: ScenarioSpec) -> str:
    """YAML-flavored dump of spec.pass1_metrics for prompt injection."""
    raise NotImplementedError("Phase B.2")


def _format_tier_topology_description(spec: ScenarioSpec) -> str:
    """Prose summary of tier topology for prompt context."""
    raise NotImplementedError("Phase B.2")


def _format_healthy_baselines_block() -> str:
    """Inline excerpts from docs/internal/healthy-baselines.md for prompt context.

    Returns the per-tier "Compute / Database / Cache / Network tier" sections
    of healthy-baselines.md so the LLM knows the healthy ranges to default to
    when the scenario doesn't override.
    """
    raise NotImplementedError("Phase B.2")
