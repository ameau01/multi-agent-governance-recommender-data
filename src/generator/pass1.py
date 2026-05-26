"""Pass 1 generator — base time-series per tier.

Strategy: ONE LLM call per active tier (not one call for all four tiers at
once). For each call, ask for 1344 records for the requested tier and empty
arrays for the others. This bounds per-call output size to ~50-95K tokens
(within Sonnet 4.6's 64K output limit for most scenarios).

Known limitation: Scenario 5 (per-instance compute, 10752 records) exceeds
the single-call budget. Per-instance chunking is a future enhancement;
flagged with a clear warning when encountered.

Validation: each emitted record is validated against the corresponding
Pydantic record class (ComputeRecord, DatabaseRecord, etc.). Timestamps
must be exactly 15 minutes apart starting from DATA_WINDOW_START_UTC.
Up to 3 retry attempts on parse or validation failure.

See docs/internal/generation-methodology.md §2 for the full Pass 1 contract.
"""

from __future__ import annotations
import json
from datetime import timedelta
from pathlib import Path
from typing import Type

import yaml
from pydantic import BaseModel, ValidationError

from contracts import (
    CacheRecord,
    ComputeRecord,
    DatabaseRecord,
    NetworkRecord,
)
from generator.checkpoint import checkpoint_path, write_pydantic_atomic
from generator.constants import (
    DATA_WINDOW_START_UTC,
    HEALTHY_BASELINES_PATH,
    INTERMEDIATES_DIR,
    INTERVAL_MINUTES,
    PASS1_MODEL,
    PASS1_PROMPT_PATH,
    RECORDS_PER_TIER,
)
from generator.llm_client import LLMClient
from generator.types import Pass1Output, ScenarioSpec


_TIER_MODELS: dict[str, Type[BaseModel]] = {
    "compute": ComputeRecord,
    "database": DatabaseRecord,
    "cache": CacheRecord,
    "network": NetworkRecord,
}

_TIER_KEYS = {
    "compute": "Compute_Metrics",
    "database": "Database_Metrics",
    "cache": "Cache_Metrics",
    "network": "Network_Metrics",
}

_MAX_RETRIES = 3
_PASS1_MAX_TOKENS = 64000


def active_tiers(spec: ScenarioSpec) -> list[str]:
    """Tier names with present=true in the spec, in canonical order."""
    return [
        t for t in ("compute", "database", "cache", "network")
        if (entry := spec.tier_topology.get(t)) and entry.get("present", True)
    ]


def generate_pass1(
    spec: ScenarioSpec,
    *,
    intermediates_dir: Path | None = None,
) -> Pass1Output:
    """Run Pass 1 for one scenario, one tier at a time.

    Args:
        spec: Loaded scenario spec.
        intermediates_dir: Where per-call LLM logs go. Defaults to INTERMEDIATES_DIR.

    Returns:
        Pass1Output with one or more tier arrays populated (1344 records each),
        and the remaining tier arrays as [].

    Raises:
        RuntimeError: if Pass 1 fails for any tier after 3 retries.
    """
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    if spec.scenario_id == "05":
        print(
            "  WARNING: Scenario 05 emits per-instance compute records (10752 total). "
            "This exceeds Sonnet 4.6's 64K output token limit in a single call. "
            "Pass 1 may fail; per-instance chunking is needed (future enhancement)."
        )

    client = LLMClient(model=PASS1_MODEL, max_tokens=_PASS1_MAX_TOKENS)
    healthy_baselines = HEALTHY_BASELINES_PATH.read_text(encoding="utf-8")

    tiers = active_tiers(spec)
    if not tiers:
        raise ValueError(f"Scenario {spec.scenario_id}: no active tiers in tier_topology")

    # Each tier becomes its own LLM call. Per-tier results are slotted into
    # the combined Pass1Output. Tiers not in `tiers` stay as [].
    arrays: dict[str, list[dict]] = {
        "Compute_Metrics": [],
        "Database_Metrics": [],
        "Cache_Metrics": [],
        "Network_Metrics": [],
    }
    for tier in tiers:
        print(f"  Pass 1 [{spec.scenario_id}] {tier}: requesting {RECORDS_PER_TIER} records...")
        records = _generate_single_tier(
            client=client,
            spec=spec,
            tier=tier,
            healthy_baselines=healthy_baselines,
            intermediates_dir=intermediates_dir,
        )
        arrays[_TIER_KEYS[tier]] = [r.model_dump(mode="json") for r in records]
        print(f"  Pass 1 [{spec.scenario_id}] {tier}: ✓ {len(records)} records validated")

    return Pass1Output(
        scenario_id=spec.scenario_id,
        Compute_Metrics=arrays["Compute_Metrics"],
        Database_Metrics=arrays["Database_Metrics"],
        Cache_Metrics=arrays["Cache_Metrics"],
        Network_Metrics=arrays["Network_Metrics"],
    )


def _generate_single_tier(
    *,
    client: LLMClient,
    spec: ScenarioSpec,
    tier: str,
    healthy_baselines: str,
    intermediates_dir: Path,
) -> list[BaseModel]:
    """One LLM call for one tier. Up to _MAX_RETRIES on failure."""
    substitutions = _build_substitutions(
        spec, tiers_required=tier, healthy_baselines_block=healthy_baselines,
    )
    log_path = intermediates_dir / spec.scenario_id / f"pass1_{tier}_llm_log.json"

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.call(
                prompt_path=PASS1_PROMPT_PATH,
                substitutions=substitutions,
                log_path=log_path,
                metadata={
                    "scenario_id": spec.scenario_id,
                    "phase": "pass1",
                    "tier": tier,
                    "attempt": attempt,
                },
            )
            return _parse_and_validate_tier(response, tier, spec.scenario_id)
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = e
            print(f"    attempt {attempt}/{_MAX_RETRIES} failed: {type(e).__name__}: {e}")

    raise RuntimeError(
        f"Pass 1 failed for scenario {spec.scenario_id} tier {tier} "
        f"after {_MAX_RETRIES} attempts. Last error: {last_error}"
    )


def _parse_and_validate_tier(
    response: str, tier: str, scenario_id: str,
) -> list[BaseModel]:
    """Parse the JSON response, extract this tier's array, validate every record."""
    data = json.loads(response)
    tier_key = _TIER_KEYS[tier]
    raw = data.get(tier_key)
    if not isinstance(raw, list):
        raise ValueError(
            f"Scenario {scenario_id} {tier}: expected {tier_key} to be a list, "
            f"got {type(raw).__name__}"
        )
    expected_count = RECORDS_PER_TIER
    if scenario_id == "05" and tier == "compute":
        # Per-instance compute records: N instances × 1344 timestamps
        compute_count = spec_compute_instance_count(scenario_id)
        expected_count = compute_count * RECORDS_PER_TIER
    if len(raw) != expected_count:
        raise ValueError(
            f"Scenario {scenario_id} {tier}: expected {expected_count} records, "
            f"got {len(raw)}"
        )
    model_cls = _TIER_MODELS[tier]
    records = [model_cls.model_validate(r) for r in raw]
    _verify_timestamps(records, tier, scenario_id)
    return records


def spec_compute_instance_count(scenario_id: str) -> int:
    """For Scenario 5, return the number of compute instances. Defaults to 8."""
    if scenario_id == "05":
        return 8
    return 1


def _verify_timestamps(records: list, tier: str, scenario_id: str) -> None:
    """Confirm 15-minute monotonic timestamps starting at DATA_WINDOW_START_UTC.

    For Scenario 5 per-instance records, expect groups of N records sharing
    each timestamp (one per instance) — checked as: timestamps repeat in
    blocks of N where N = compute_instance_count.
    """
    if scenario_id == "05" and tier == "compute":
        # Per-instance records: every N consecutive records share a timestamp,
        # then the next N have the next timestamp 15min later.
        instance_count = spec_compute_instance_count(scenario_id)
        expected = DATA_WINDOW_START_UTC
        for i in range(0, len(records), instance_count):
            block = records[i : i + instance_count]
            for r in block:
                if r.timestamp != expected:
                    raise ValueError(
                        f"Scenario {scenario_id} {tier} [{i}]: timestamp {r.timestamp} "
                        f"!= expected {expected}"
                    )
            expected += timedelta(minutes=INTERVAL_MINUTES)
        return

    expected = DATA_WINDOW_START_UTC
    for i, r in enumerate(records):
        if r.timestamp != expected:
            raise ValueError(
                f"Scenario {scenario_id} {tier} [{i}]: timestamp {r.timestamp} "
                f"!= expected {expected}"
            )
        expected += timedelta(minutes=INTERVAL_MINUTES)


# ============================================================
# Substitution builders (per-prompt placeholder values)
# ============================================================
def _build_substitutions(
    spec: ScenarioSpec,
    *,
    tiers_required: str,
    healthy_baselines_block: str,
) -> dict[str, object]:
    """Build the dict passed to LLMClient.call()'s substitutions parameter.

    `tiers_required` is a single tier name (e.g. "compute"). The prompt
    tells the LLM to emit non-empty arrays only for tiers listed here.
    """
    bc = spec.business_context or {}
    return {
        "scenario_id": spec.scenario_id,
        "scenario_name": spec.scenario_name,
        "scenario_type": spec.scenario_type,
        "tiers_required": tiers_required,
        "business_context_description": bc.get("description", ""),
        "sla_target_description": bc.get(
            "sla_target_description",
            f"{bc.get('sla_target_availability_pct', 99.5)}% availability, "
            f"P95 < {bc.get('sla_target_p95_ms', 500)}ms",
        ),
        "criticality": bc.get("criticality", "tier-2"),
        "tier_topology_description": _format_tier_topology(spec),
        "pass1_metrics_block": _format_pass1_metrics(spec, tiers_required),
        "healthy_baselines_block": healthy_baselines_block,
    }


def _format_tier_topology(spec: ScenarioSpec) -> str:
    """Prose summary of active tiers + their key attributes."""
    lines = []
    for tier in ("compute", "database", "cache", "network"):
        entry = spec.tier_topology.get(tier)
        if not entry or not entry.get("present", True):
            continue
        attrs = ", ".join(
            f"{k}={v}" for k, v in entry.items()
            if k != "present" and v is not None
        )
        lines.append(f"  - {tier}: {attrs}")
    return "\n".join(lines) if lines else "  (no tiers)"


def _format_pass1_metrics(spec: ScenarioSpec, tier: str) -> str:
    """YAML-style dump of just the requested tier's pass1_metrics block."""
    tier_metrics = spec.pass1_metrics.get(tier, {})
    return yaml.dump({tier: tier_metrics}, default_flow_style=False, sort_keys=False)


# ============================================================
# Intermediate file IO
# ============================================================
def write_pass1_intermediate(output: Pass1Output, intermediates_dir: Path) -> Path:
    """Persist Pass1Output atomically to intermediates/NN/pass1.json."""
    target = checkpoint_path(output.scenario_id, "pass1", intermediates_dir)
    write_pydantic_atomic(target, output)
    return target


def read_pass1_intermediate(scenario_id: str, intermediates_dir: Path) -> Pass1Output:
    """Load a previously-written Pass1Output. Raises if missing or invalid."""
    target = checkpoint_path(scenario_id, "pass1", intermediates_dir)
    if not target.exists():
        raise FileNotFoundError(
            f"Pass 1 intermediate not found: {target}. Run pass1 for {scenario_id} first."
        )
    with target.open(encoding="utf-8") as f:
        data = json.load(f)
    return Pass1Output.model_validate(data)
