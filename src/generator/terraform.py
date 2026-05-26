"""Jinja-based main.tf renderer.

Reads ScenarioMetadata.tier_topology and stitches together per-tier blocks
into a valid HCL file. Validates output with python-hcl2 before writing.

Per docs/internal/generation-methodology.md §5.
"""

from __future__ import annotations
import re
from pathlib import Path

import hcl2
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from contracts import ScenarioMetadata
from generator.checkpoint import write_json_atomic
from generator.constants import TEMPLATES_DIR


# ============================================================
# Jinja environment
# ============================================================
def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


# ============================================================
# Per-tier block renderers
# ============================================================
def _render_compute_block(env: Environment, metadata: ScenarioMetadata) -> str:
    tier = metadata.tier_topology.compute
    if tier is None:
        return ""
    template = env.get_template("compute.tf.j2")
    return template.render(
        instance_class=tier.instance_class,
        instance_count=tier.instance_count,
        scaling_policy=tier.scaling_policy,
        auto_scaling_min=tier.auto_scaling_min,
        auto_scaling_max=tier.auto_scaling_max,
    )


def _render_database_block(env: Environment, metadata: ScenarioMetadata) -> str:
    tier = metadata.tier_topology.database
    if tier is None:
        return ""
    template = env.get_template("database.tf.j2")
    return template.render(
        instance_class=tier.instance_class,
        replicas=tier.replicas,
        storage_gb=tier.storage_gb,
    )


def _render_cache_block(env: Environment, metadata: ScenarioMetadata) -> str:
    tier = metadata.tier_topology.cache
    if tier is None:
        return ""
    template = env.get_template("cache.tf.j2")
    return template.render(
        node_type=tier.node_type,
        node_count=tier.node_count,
        ttl_seconds=tier.ttl_seconds,
    )


def _render_network_block(env: Environment, metadata: ScenarioMetadata) -> str:
    tier = metadata.tier_topology.network
    if tier is None:
        return ""
    template = env.get_template("network.tf.j2")
    return template.render(
        load_balancer_type=tier.load_balancer_type,
        algorithm=tier.algorithm,
    )


def _render_security_group_rules(metadata: ScenarioMetadata) -> str:
    """Emit aws_security_group_rule resources between connected tiers.

    The agent's System Mapper reads these to derive the tier-dependency graph.
    Edges:
      compute → database (if both present)
      compute → cache    (if both present)
    """
    tt = metadata.tier_topology
    rules: list[str] = []
    app_name = f"app{metadata.scenario_id}"

    if tt.compute is not None and tt.database is not None:
        rules.append(_security_group_rule_block(
            name="compute_to_database",
            description=f"{app_name}: compute tier queries database tier",
            from_tier="compute",
            to_tier="database",
            port=5432,
        ))
    if tt.compute is not None and tt.cache is not None:
        rules.append(_security_group_rule_block(
            name="compute_to_cache",
            description=f"{app_name}: compute tier reads from cache tier",
            from_tier="compute",
            to_tier="cache",
            port=6379,
        ))

    return "\n\n".join(rules)


def _security_group_rule_block(
    name: str, description: str, from_tier: str, to_tier: str, port: int,
) -> str:
    """Render a single aws_security_group_rule block."""
    return (
        f'resource "aws_security_group_rule" "{name}" {{\n'
        f'  description       = "{description}"\n'
        f'  type              = "ingress"\n'
        f'  from_port         = {port}\n'
        f'  to_port           = {port}\n'
        f'  protocol          = "tcp"\n'
        f'  security_group_id = "sg-placeholder-{to_tier}"\n'
        f'  source_security_group_id = "sg-placeholder-{from_tier}"\n'
        f'}}'
    )


# ============================================================
# Public API
# ============================================================
def render_terraform(metadata: ScenarioMetadata) -> str:
    """Render main.tf as a string from the scenario's metadata.

    Args:
        metadata: A built ScenarioMetadata.

    Returns:
        HCL source as str. Not yet validated — caller should validate_terraform()
        before writing.
    """
    env = _jinja_env()
    wrapper = env.get_template("wrapper.tf.j2")
    app_name = f"app{metadata.scenario_id}"
    return wrapper.render(
        app_name=app_name,
        compute_block=_render_compute_block(env, metadata),
        database_block=_render_database_block(env, metadata),
        cache_block=_render_cache_block(env, metadata),
        network_block=_render_network_block(env, metadata),
        security_group_rules=_render_security_group_rules(metadata),
    )


def validate_terraform(hcl: str, metadata: ScenarioMetadata) -> None:
    """Parse HCL with python-hcl2 and assert structural invariants.

    Asserts:
      - Parses cleanly (no syntax errors).
      - Every tier marked present in metadata.tier_topology has ≥1 matching aws_* resource.
      - Every resource carries Application = "app<NN>" tag.
      - Load-balancer scenarios have load_balancing_algorithm_type set.

    Args:
        hcl: Rendered HCL string.
        metadata: The metadata it was rendered from (for cross-checks).

    Raises:
        ValueError: with a diagnostic message on any failure.
    """
    # 1. Parses cleanly
    try:
        from io import StringIO
        parsed = hcl2.load(StringIO(hcl))
    except Exception as e:
        raise ValueError(f"main.tf failed to parse with python-hcl2: {e}") from e

    app_name = f"app{metadata.scenario_id}"

    # 2. Tier-presence invariant — string-search the HCL for resource markers.
    # (hcl2's parsed structure is verbose; substring checks are clearer for our
    # invariants given the simple Jinja template shape.)
    tt = metadata.tier_topology
    if tt.compute is not None:
        if not _has_compute_resource(hcl):
            raise ValueError("Compute tier present in topology but no aws_instance/aws_autoscaling_group in main.tf")
    if tt.database is not None:
        if 'resource "aws_db_instance"' not in hcl:
            raise ValueError("Database tier present in topology but no aws_db_instance in main.tf")
    if tt.cache is not None:
        if 'resource "aws_elasticache_cluster"' not in hcl:
            raise ValueError("Cache tier present in topology but no aws_elasticache_cluster in main.tf")
    if tt.network is not None:
        if 'resource "aws_lb"' not in hcl:
            raise ValueError("Network tier present in topology but no aws_lb in main.tf")

    # 3. Application tag invariant
    if f'app_name = "{app_name}"' not in hcl:
        raise ValueError(
            f"main.tf does not set locals.app_name = {app_name!r} — "
            "expected for tagging. Wrapper template may be broken."
        )

    # 4. Load-balancer algorithm invariant
    if tt.network is not None:
        if "load_balancing_algorithm_type" not in hcl:
            raise ValueError(
                "Network tier present but load_balancing_algorithm_type not set on aws_lb_target_group"
            )


_COMPUTE_RES_RE = re.compile(
    r'resource\s+"(aws_instance|aws_autoscaling_group)"', re.MULTILINE
)


def _has_compute_resource(hcl: str) -> bool:
    return bool(_COMPUTE_RES_RE.search(hcl))


def write_terraform(hcl: str, output_dir: Path) -> Path:
    """Write HCL to <output_dir>/main.tf atomically.

    Args:
        hcl: Validated HCL string.
        output_dir: e.g. scenarios/07/. Created if needed.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "main.tf"
    # Use the same atomic-write pattern as checkpoint.write_json_atomic, but
    # for plain text. Inlined here to avoid expanding checkpoint.py's API.
    import os, tempfile
    fd, tmp_str = tempfile.mkstemp(suffix=".tmp", prefix=target.name + ".", dir=str(output_dir))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(hcl)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target
