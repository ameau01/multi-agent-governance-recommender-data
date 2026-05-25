"""Jinja-based main.tf renderer.

Reads ScenarioMetadata.tier_topology and emits valid HCL using per-tier templates
under `templates/`. Validates output with `python-hcl2` before writing.

The Terraform is the single source of truth for tier topology — it must match
the metadata exactly. Drift between the two would break the agent's System Mapper.

See `docs/internal/generation-methodology.md` §5 for the full per-tier rendering
contract.
"""

from __future__ import annotations
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from generator.constants import TEMPLATES_DIR
# from contracts.metadata import ScenarioMetadata   # uncomment after Phase A.1


def _jinja_env() -> Environment:
    """Construct the Jinja env. StrictUndefined catches missing template variables."""
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_terraform(metadata: "ScenarioMetadata") -> str:  # type: ignore[name-defined]
    """Render `main.tf` HCL for one scenario.

    For each tier marked `present: true` in `metadata.tier_topology`, render the
    corresponding tier template. Stitch all blocks together via `wrapper.tf.j2`,
    which provides the `terraform` block, `provider "aws"`, and `locals`.

    Tag invariants (enforced by validate_terraform):
      - Every resource carries `Application = "app<NN>"`
      - Every resource carries `Tier = "<tier_name>"`
      - Load-balancer scenarios set `load_balancing_algorithm_type`
      - Multi-tier scenarios emit `aws_security_group_rule` between relevant tiers

    Args:
        metadata: A built ScenarioMetadata.

    Returns:
        HCL string. Not yet validated — caller should validate_terraform() before writing.
    """
    raise NotImplementedError("Phase A.4 — see BUILD_PLAN.md §A.4")


def validate_terraform(hcl: str, metadata: "ScenarioMetadata") -> None:  # type: ignore[name-defined]
    """Parse the HCL with `python-hcl2` and assert structural invariants.

    Asserts:
      - Parses cleanly (no syntax errors).
      - Every tier marked present in metadata.tier_topology has ≥1 matching aws_* resource.
      - Every resource carries Application and Tier tags.
      - Load-balancer scenarios have load_balancing_algorithm_type set.

    Args:
        hcl: Rendered HCL string.
        metadata: The metadata it was rendered from (for cross-checks).

    Raises:
        ValueError: with a diagnostic message on any failure.
    """
    raise NotImplementedError("Phase A.4 — see BUILD_PLAN.md §A.4")


def write_terraform(hcl: str, output_dir: Path) -> Path:
    """Write HCL to `<output_dir>/main.tf`."""
    raise NotImplementedError("Phase A.4 — see BUILD_PLAN.md §A.4")
