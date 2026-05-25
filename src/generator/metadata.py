"""Programmatic ScenarioMetadata builder.

Reads a loaded ScenarioSpec and emits a Pydantic-validated `scenarios/NN/metadata.json`.
Deterministic — no LLM involvement.

See `docs/internal/generation-methodology.md` §4 for the per-field mapping rules
and `docs/internal/generation-conventions.md` §§5–8 for the SLA / cost / topology
derivation conventions.
"""

from __future__ import annotations
from pathlib import Path

from generator.types import ScenarioSpec
# from contracts.metadata import ScenarioMetadata   # uncomment after Phase A.1


def build_metadata(spec: ScenarioSpec) -> "ScenarioMetadata":  # type: ignore[name-defined]
    """Build a contract-conformant ScenarioMetadata object from a spec.

    Performs the per-field mappings documented in `docs/internal/generation-methodology.md` §4:
      - contract_version ← `contracts.version.CONTRACT_VERSION`
      - generated_at ← current UTC timestamp
      - scenario_type str → ScenarioType enum
      - tier_topology absent/false tiers → None
      - cost_baseline.by_tier auto-filled with 0.0 for absent tiers
      - monthly_cost_total_usd auto-computed from by_tier sum
      - sla_target_description derived per generation-conventions.md §6
      - telemetry_file_pointers → defaults
      - infrastructure_file → "main.tf"
      - action_category mapped through ActionCategory enum (allow None)
      - primary_tier / secondary_tier mapped through TierName enum (allow None)

    Args:
        spec: Loaded scenario spec.

    Returns:
        ScenarioMetadata, Pydantic-validated on construction.

    Raises:
        pydantic.ValidationError: if the derived metadata doesn't conform to the contract.
    """
    raise NotImplementedError("Phase A.3 — see BUILD_PLAN.md §A.3")


def write_metadata(metadata: "ScenarioMetadata", output_dir: Path) -> Path:  # type: ignore[name-defined]
    """Serialize ScenarioMetadata to `<output_dir>/metadata.json`.

    Uses `model_dump_json(indent=2)` for stable, diff-friendly output.

    Args:
        metadata: A built ScenarioMetadata.
        output_dir: e.g. `scenarios/01/`.

    Returns:
        The path to the written file.
    """
    raise NotImplementedError("Phase A.3 — see BUILD_PLAN.md §A.3")


def derive_sla_description(p95_ms: int, availability_pct: float) -> str:
    """Derive `sla_target_description` from structured SLA fields.

    Format per `docs/internal/generation-conventions.md` §6.
    """
    return f"{availability_pct}% availability, P95 < {p95_ms}ms"
