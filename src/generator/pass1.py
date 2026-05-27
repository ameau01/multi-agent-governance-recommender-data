"""Pass 1 generator — day-chunked base telemetry per tier.

Strategy: ONE LLM call per (tier, day) chunk. Each call generates exactly
96 records for one tier on one specific day, well within Sonnet 4.6's
16K-per-chunk output budget.

For each scenario:
  For each active tier in the topology:
    For each of 14 days (PASS1_CHUNK_DAYS=1):
      - Check if intermediates/NN/pass1_<tier>_day<NN>.json exists
        (skip if so — resume support per chunk)
      - Call LLM with chunk-specific prompt (1 day + 1 tier)
      - Validate 96 records against Pydantic
      - Save chunk checkpoint atomically
      - Per-chunk retry up to MAX_RETRIES
      - Inter-chunk delay to be gentle on rate limits
    Concatenate 14 days into one 1344-record tier array
  Aggregate tier arrays into Pass1Output, persist to intermediates/NN/pass1.json

Why chunked:
  - Each call's output is ~9K tokens (vs ~128K for single-call), no truncation
  - Per-chunk granularity for retry, recovery from interrupt, progress visibility
  - Prompt caching pays off massively: SYSTEM + USER boilerplate identical
    across all 14 chunks of one tier, so 1 cache write + 13 reads (≈70% savings on input)
  - Works on Haiku, Sonnet, Opus (all support ≥16K output)

Scenario 5 (per-instance compute) caveat:
  Currently emits per-instance records in a single per-day chunk (768 records
  per day across 8 instances). This exceeds 16K output. Special-case handling
  is a future enhancement; flagged with a warning when encountered.

See docs/internal/generation-methodology.md §2.
"""

from __future__ import annotations
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Type


def _log(msg: str = "", *, end: str = "\n") -> None:
    """Print one progress line prefixed with [HH:MM:SS], always flushed.

    Plain-print fallback for empty / whitespace-only lines so we don't pollute
    spacing with stamps where they aren't helpful.
    """
    if not msg.strip():
        print(msg, end=end, flush=True)
        return
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", end=end, flush=True)

import yaml
from pydantic import BaseModel, ValidationError

from contracts import (
    CacheRecord,
    ComputeRecord,
    DatabaseRecord,
    NetworkRecord,
)
from generator.checkpoint import (
    chunk_checkpoint_path,
    chunk_llm_log_path,
    checkpoint_path,
    partition_chunks,
    read_json,
    write_json_atomic,
    write_pydantic_atomic,
)
from generator.constants import (
    CHUNK_RETRY_BACKOFF_SEC,
    DATA_WINDOW_DAYS,
    DATA_WINDOW_START_UTC,
    HEALTHY_BASELINES_PATH,
    INTERMEDIATES_DIR,
    INTERVAL_MINUTES,
    INTER_CHUNK_DELAY_SEC,
    MAX_RETRIES,
    PASS1_CHUNK_MAX_TOKENS,
    PASS1_MODEL,
    PASS1_PROMPT_PATH,
    PASS1_TEMPERATURE,
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

_RECORDS_PER_DAY = 96  # 24 * 4 (15-min intervals)
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def active_tiers(spec: ScenarioSpec) -> list[str]:
    """Tier names that Pass 1 should generate telemetry for.

    A tier is "active for Pass 1" only when BOTH conditions hold:

      1. `tier_topology.<tier>.present` is True (or unset, which defaults
         to True per metadata convention). This signals the tier exists
         in the application architecture.

      2. `pass1_metrics.<tier>` is a non-empty mapping. This signals
         the spec author wants Pass 1 to synthesize telemetry for it.

    The two conditions can diverge — see scenario 05's network tier:
    `tier_topology.network.present=True` (the spec is about an ALB, so
    network exists in the architecture) but `pass1_metrics.network` is
    absent (the diagnostic signal lives in the compute tier's p50/p95
    spread, not in network telemetry). In that case Pass 1 should
    NOT try to generate network data from an empty metric spec —
    that produces an underspecified prompt that some models respond
    to with chain-of-thought, breaking the JSON-only contract.
    """
    return [
        t for t in ("compute", "database", "cache", "network")
        if (entry := spec.tier_topology.get(t)) and entry.get("present", True)
        and isinstance(spec.pass1_metrics.get(t), dict)
        and spec.pass1_metrics.get(t)  # non-empty mapping
    ]


# ============================================================
# Public API: generate Pass 1 for one scenario
# ============================================================
def generate_pass1(
    spec: ScenarioSpec,
    *,
    intermediates_dir: Path | None = None,
) -> Pass1Output:
    """Run Pass 1 for one scenario, chunked per (tier, day).

    Each (tier, day) chunk is checkpointed independently. Re-running this
    function after an interruption re-uses any chunks that completed
    successfully — only missing/corrupt chunks get re-generated.

    Args:
        spec: Loaded scenario spec.
        intermediates_dir: Where chunks and LLM logs go. Defaults to INTERMEDIATES_DIR.

    Returns:
        Pass1Output with tier arrays filled (1344 records each) for active tiers.

    Raises:
        RuntimeError: if a chunk fails all MAX_RETRIES attempts.
    """
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    if spec.scenario_id == "05":
        _log(
            "  WARNING: Scenario 05 emits per-instance compute records. The current "
            "day-chunked Pass 1 generates one chunk per (tier, day); for Scenario 05 "
            "that's 768 records (8 instances × 96 timestamps) ≈ 73K tokens, exceeding "
            "the 16K chunk budget. Per-instance chunking is a future enhancement; "
            "Pass 1 for Scenario 05 may fail at chunk validation. Other scenarios are fine."
        )

    client = LLMClient(
        model=PASS1_MODEL,
        max_tokens=PASS1_CHUNK_MAX_TOKENS,
        temperature=PASS1_TEMPERATURE,
    )
    healthy_baselines = HEALTHY_BASELINES_PATH.read_text(encoding="utf-8")

    tiers = active_tiers(spec)
    if not tiers:
        raise ValueError(f"Scenario {spec.scenario_id}: no active tiers in tier_topology")

    arrays: dict[str, list[dict]] = {
        "Compute_Metrics": [],
        "Database_Metrics": [],
        "Cache_Metrics": [],
        "Network_Metrics": [],
    }
    for tier in tiers:
        _log("")
        _log(f"  ===== Pass 1 [{spec.scenario_id}] tier={tier} =====")
        records = _generate_tier_chunked(
            client=client,
            spec=spec,
            tier=tier,
            healthy_baselines=healthy_baselines,
            intermediates_dir=intermediates_dir,
        )
        arrays[_TIER_KEYS[tier]] = [r.model_dump(mode="json") for r in records]
        _log(f"  ===== Pass 1 [{spec.scenario_id}] tier={tier}: ✓ {len(records)} records aggregated =====")

    return Pass1Output(
        scenario_id=spec.scenario_id,
        Compute_Metrics=arrays["Compute_Metrics"],
        Database_Metrics=arrays["Database_Metrics"],
        Cache_Metrics=arrays["Cache_Metrics"],
        Network_Metrics=arrays["Network_Metrics"],
    )


# ============================================================
# Tier-level: loop 14 days, with resume support
# ============================================================
def _generate_tier_chunked(
    *,
    client: LLMClient,
    spec: ScenarioSpec,
    tier: str,
    healthy_baselines: str,
    intermediates_dir: Path,
) -> list[BaseModel]:
    """Generate 14 day-chunks for one tier, with per-chunk resume."""
    model_cls = _TIER_MODELS[tier]

    # Resume: detect which days are already checkpointed
    partition = partition_chunks(
        scenario_id=spec.scenario_id,
        phase="pass1",
        tier=tier,
        days=DATA_WINDOW_DAYS,
        intermediates_dir=intermediates_dir,
    )
    if partition.completed:
        _log(
            f"  Resume: {len(partition.completed)} day(s) already checkpointed, "
            f"{len(partition.remaining)} day(s) remaining"
        )

    # Generate any remaining chunks
    for day_index in partition.remaining:
        _log(f"  Day {day_index + 1}/{DATA_WINDOW_DAYS}: generating chunk for tier={tier}...")
        records = _generate_chunk_with_retry(
            client=client,
            spec=spec,
            tier=tier,
            day_index=day_index,
            healthy_baselines=healthy_baselines,
            intermediates_dir=intermediates_dir,
        )
        # Atomically save the chunk checkpoint
        chunk_path = chunk_checkpoint_path(
            spec.scenario_id, "pass1", tier, day_index, intermediates_dir,
        )
        write_json_atomic(
            chunk_path,
            [r.model_dump(mode="json") for r in records],
        )
        _log(f"  Day {day_index + 1}/{DATA_WINDOW_DAYS}: ✓ saved {chunk_path.name}")
        if INTER_CHUNK_DELAY_SEC > 0:
            time.sleep(INTER_CHUNK_DELAY_SEC)

    # Load + aggregate all 14 days in order
    all_records: list[BaseModel] = []
    for day_index in range(DATA_WINDOW_DAYS):
        chunk_path = chunk_checkpoint_path(
            spec.scenario_id, "pass1", tier, day_index, intermediates_dir,
        )
        raw = read_json(chunk_path)
        records = [model_cls.model_validate(r) for r in raw]
        if len(records) != _RECORDS_PER_DAY:
            raise RuntimeError(
                f"Chunk {chunk_path.name} has {len(records)} records, expected {_RECORDS_PER_DAY}"
            )
        all_records.extend(records)

    # Sanity check: total record count.
    #
    # Historical note: scenario 05's spec sets `pass1_metrics.compute.per_instance:
    # True` and `tier_topology.compute.instance_count: 8`, which was a design
    # intent to emit one record per timestamp per instance (1344 × 8 = 10752).
    # In practice the chunker emits one record per timestamp regardless, and the
    # per-instance hot/cold signal flows through `scenario_specific_evidence.
    # per_instance_breakdown` in metadata.json — that's the load-bearing input
    # for the downstream agent. The 8× expectation was an unimplemented feature
    # masquerading as a bug, so we drop the special case and let scenario 05
    # behave like every other single-tier scenario at 1344 fleet-aggregate
    # records. The per_instance_breakdown still tells the agent which instances
    # are hot vs cold.
    expected_total = RECORDS_PER_TIER
    if len(all_records) != expected_total:
        raise RuntimeError(
            f"Aggregated {tier} record count: {len(all_records)}, expected {expected_total}"
        )

    return all_records


# ============================================================
# Chunk-level: one LLM call with retries
# ============================================================
def _generate_chunk_with_retry(
    *,
    client: LLMClient,
    spec: ScenarioSpec,
    tier: str,
    day_index: int,
    healthy_baselines: str,
    intermediates_dir: Path,
) -> list[BaseModel]:
    """One LLM call for one (tier, day) chunk. Up to MAX_RETRIES attempts."""
    substitutions = _build_chunk_substitutions(
        spec=spec,
        tier=tier,
        day_index=day_index,
        healthy_baselines_block=healthy_baselines,
    )
    log_path = chunk_llm_log_path(
        spec.scenario_id, "pass1", tier, day_index, intermediates_dir,
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.call(
                prompt_path=PASS1_PROMPT_PATH,
                substitutions=substitutions,
                log_path=log_path,
                metadata={
                    "scenario_id": spec.scenario_id,
                    "phase": "pass1",
                    "tier": tier,
                    "day_index": day_index,
                    "attempt": attempt,
                },
            )
            return _parse_and_validate_chunk(
                response, tier=tier, day_index=day_index, scenario_id=spec.scenario_id,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = e
            _log(
                f"      chunk day {day_index + 1}/{DATA_WINDOW_DAYS} attempt "
                f"{attempt}/{MAX_RETRIES} failed: {type(e).__name__}: {e}"
            )
            if attempt < MAX_RETRIES:
                if CHUNK_RETRY_BACKOFF_SEC > 0:
                    time.sleep(CHUNK_RETRY_BACKOFF_SEC)

    raise RuntimeError(
        f"Pass 1 chunk failed: scenario {spec.scenario_id} tier {tier} "
        f"day {day_index + 1}/{DATA_WINDOW_DAYS} after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _parse_and_validate_chunk(
    response: str, *, tier: str, day_index: int, scenario_id: str,
) -> list[BaseModel]:
    """Parse the chunk's JSON response, extract this tier's records, validate."""
    data = json.loads(response)
    tier_key = _TIER_KEYS[tier]
    raw = data.get(tier_key)
    if not isinstance(raw, list):
        raise ValueError(
            f"Scenario {scenario_id} {tier} day {day_index}: expected "
            f"{tier_key} to be a list, got {type(raw).__name__}"
        )
    if len(raw) != _RECORDS_PER_DAY:
        raise ValueError(
            f"Scenario {scenario_id} {tier} day {day_index}: expected "
            f"{_RECORDS_PER_DAY} records, got {len(raw)}"
        )
    model_cls = _TIER_MODELS[tier]
    records = [model_cls.model_validate(r) for r in raw]
    _verify_chunk_timestamps(records, tier=tier, day_index=day_index, scenario_id=scenario_id)
    return records


def _verify_chunk_timestamps(
    records: list[BaseModel], *, tier: str, day_index: int, scenario_id: str,
) -> None:
    """Each chunk's 96 records have timestamps for one specific day."""
    day_start = DATA_WINDOW_START_UTC + timedelta(days=day_index)
    expected = day_start
    for i, r in enumerate(records):
        # Pydantic deserializes 'Z' suffix to UTC datetime; compare aware datetimes
        ts = r.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts != expected:
            raise ValueError(
                f"Scenario {scenario_id} {tier} day {day_index + 1} record [{i}]: "
                f"timestamp {r.timestamp} != expected {expected}"
            )
        expected += timedelta(minutes=INTERVAL_MINUTES)


# ============================================================
# Substitution builder (per chunk)
# ============================================================
def _build_chunk_substitutions(
    *,
    spec: ScenarioSpec,
    tier: str,
    day_index: int,
    healthy_baselines_block: str,
) -> dict[str, object]:
    """Build the dict passed to LLMClient.call()'s substitutions parameter for one chunk."""
    day_date_obj = DATA_WINDOW_START_UTC.date() + timedelta(days=day_index)
    day_date_str = day_date_obj.isoformat()
    weekday_index = day_date_obj.weekday()  # Monday=0
    day_of_week_name = _WEEKDAY_NAMES[weekday_index]
    is_weekend = weekday_index >= 5
    period_type = "weekend day" if is_weekend else "weekday business day"

    bc = spec.business_context or {}
    narrative = spec.narrative or {}
    behavioral_notes = (narrative.get("what_this_demonstrates") or "").strip()
    if not behavioral_notes:
        behavioral_notes = "(no narrative cue provided)"
    return {
        "scenario_id": spec.scenario_id,
        "scenario_name": spec.scenario_name,
        "scenario_type": spec.scenario_type,
        "tiers_required": tier,
        "business_context_description": bc.get("description", ""),
        "sla_target_description": bc.get(
            "sla_target_description",
            f"{bc.get('sla_target_availability_pct', 99.5)}% availability, "
            f"P95 < {bc.get('sla_target_p95_ms', 500)}ms",
        ),
        "criticality": bc.get("criticality", "tier-2"),
        "scenario_behavioral_notes": behavioral_notes,
        "tier_topology_description": _format_tier_topology(spec),
        "pass1_metrics_block": _format_pass1_metrics(spec, tier),
        "healthy_baselines_block": healthy_baselines_block,
        # Chunk-specific placeholders
        "day_index": day_index + 1,                    # 1-indexed for humans
        "day_date": day_date_str,
        "day_of_week": day_of_week_name,
        "day_period_type": period_type,
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
# Intermediate file IO (final per-scenario Pass1Output)
# ============================================================
def write_pass1_intermediate(output: Pass1Output, intermediates_dir: Path) -> Path:
    """Persist the aggregated Pass1Output atomically to intermediates/NN/pass1.json."""
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
