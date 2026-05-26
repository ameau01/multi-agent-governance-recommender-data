"""Load and validate scenario spec YAMLs from `docs/internal/scenarios/`.

The 18 spec YAMLs are the canonical input to the data-gen pipeline. Each
loads into a ScenarioSpec Pydantic model (defined in generator.types) which
mirrors the YAML shape. The metadata generator, Pass 1 generator, and Pass 2
generator all start by calling load_spec(scenario_id).

See docs/internal/scenarios/07.spec.yaml for the canonical example of the
YAML shape.
"""

from __future__ import annotations
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from generator.constants import ALL_SCENARIO_IDS, SCENARIO_SPECS_DIR
from generator.types import ScenarioSpec


_SCENARIO_ID_RE = re.compile(r"^\d{2}$")


def spec_path(scenario_id: str) -> Path:
    """Return the path to a scenario's spec YAML."""
    return SCENARIO_SPECS_DIR / f"{scenario_id}.spec.yaml"


def load_spec(scenario_id: str) -> ScenarioSpec:
    """Load and validate the spec YAML for one scenario.

    Args:
        scenario_id: Zero-padded string, "01" through "18".

    Returns:
        ScenarioSpec, Pydantic-validated.

    Raises:
        ValueError: if scenario_id is malformed (not "01"-"99").
        FileNotFoundError: if the YAML doesn't exist.
        yaml.YAMLError: if the YAML is malformed.
        pydantic.ValidationError: if the YAML doesn't conform to ScenarioSpec.
    """
    if not _SCENARIO_ID_RE.match(scenario_id):
        raise ValueError(
            f"scenario_id must be a zero-padded two-digit string, got {scenario_id!r}"
        )

    path = spec_path(scenario_id)
    if not path.exists():
        raise FileNotFoundError(f"Scenario spec not found: {path}")

    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Spec YAML must be a mapping at the top level, got {type(data).__name__}: {path}"
        )

    try:
        return ScenarioSpec.model_validate(data)
    except ValidationError as e:
        raise ValidationError.from_exception_data(
            title=f"ScenarioSpec validation failed for {path}",
            line_errors=e.errors(),
        ) from e


def load_all_specs() -> list[ScenarioSpec]:
    """Load all 18 scenario specs in scenario_id order ("01" through "18").

    Returns:
        List of 18 ScenarioSpec objects.

    Raises:
        FileNotFoundError: if any scenario's spec YAML is missing. Error
            message names all missing IDs at once.
    """
    specs: list[ScenarioSpec] = []
    missing: list[str] = []
    for sid in ALL_SCENARIO_IDS:
        path = spec_path(sid)
        if not path.exists():
            missing.append(sid)
            continue
        specs.append(load_spec(sid))

    if missing:
        raise FileNotFoundError(
            f"Missing spec YAMLs for scenarios: {', '.join(missing)}. "
            f"Expected under {SCENARIO_SPECS_DIR}/."
        )

    return specs


def list_available_scenario_ids() -> list[str]:
    """Return scenario IDs that currently have a spec YAML on disk.

    Used by CLI commands that want to operate on whatever's available
    rather than the full canonical list.
    """
    if not SCENARIO_SPECS_DIR.exists():
        return []
    ids = []
    for path in sorted(SCENARIO_SPECS_DIR.glob("*.spec.yaml")):
        stem = path.stem.replace(".spec", "")
        if _SCENARIO_ID_RE.match(stem):
            ids.append(stem)
    return ids
