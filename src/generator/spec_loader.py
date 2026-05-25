"""Load and validate scenario spec YAMLs from `docs/internal/scenarios/`.

See `docs/internal/scenarios/07.spec.yaml` for the canonical example of the YAML
shape. The 13 required top-level keys are enforced by `ScenarioSpec`.
"""

from __future__ import annotations
from pathlib import Path

from generator.constants import SCENARIO_SPECS_DIR, ALL_SCENARIO_IDS
from generator.types import ScenarioSpec


def load_spec(scenario_id: str) -> ScenarioSpec:
    """Load and validate the spec YAML for one scenario.

    Args:
        scenario_id: Zero-padded string, e.g. "01" through "18".

    Returns:
        ScenarioSpec with the YAML content, validated by Pydantic.

    Raises:
        FileNotFoundError: if the YAML doesn't exist at expected path.
        pydantic.ValidationError: if the YAML doesn't conform to ScenarioSpec.
        ValueError: if scenario_id is malformed.
    """
    raise NotImplementedError("Phase A.2 — see BUILD_PLAN.md §A.2")


def load_all_specs() -> list[ScenarioSpec]:
    """Load all 18 scenario specs in scenario_id order.

    Returns:
        List of 18 ScenarioSpec objects, ordered "01" through "18".

    Raises:
        FileNotFoundError: if any scenario's spec YAML is missing.
    """
    raise NotImplementedError("Phase A.2 — see BUILD_PLAN.md §A.2")


def spec_path(scenario_id: str) -> Path:
    """Return the path to a scenario's spec YAML."""
    return SCENARIO_SPECS_DIR / f"{scenario_id}.spec.yaml"
