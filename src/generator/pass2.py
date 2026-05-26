"""Pass 2 generator — cross-tier correlation injection.

Two paths:

  1. Pass-through (no LLM call) — for scenarios with no pass2_correlations.
     Pass 2 output is byte-equal to Pass 1 (just renamed).

  2. LLM correlation injection — for scenarios with non-empty correlations.
     Calls Sonnet 4.6 with the Pass 1 JSON in the prompt, asks it to modify
     only the affected metrics in the affected time windows, then enforces
     the invariance contract programmatically.

Pass 2 also computes the consumer-facing correlation_evidence.json from the
final telemetry — Pearson coefficients computed in Python, not asked from
the model (avoid hallucination).

See docs/internal/generation-methodology.md §3 for the full Pass 2 contract.
"""

from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Type

from pydantic import BaseModel, ValidationError

from contracts import (
    CacheRecord,
    ComputeRecord,
    CorrelationPair,
    DatabaseRecord,
    NetworkRecord,
    TierName,
)
from generator.checkpoint import checkpoint_path, write_pydantic_atomic
from generator.constants import (
    INTERMEDIATES_DIR,
    PASS2_MODEL,
    PASS2_PROMPT_PATH,
    RECORDS_PER_TIER,
)
from generator.llm_client import LLMClient
from generator.types import Pass1Output, Pass2Output, ScenarioSpec


_TIER_KEYS = {
    "compute": "Compute_Metrics",
    "database": "Database_Metrics",
    "cache": "Cache_Metrics",
    "network": "Network_Metrics",
}
_TIER_MODELS: dict[str, Type[BaseModel]] = {
    "compute": ComputeRecord,
    "database": DatabaseRecord,
    "cache": CacheRecord,
    "network": NetworkRecord,
}

_MAX_RETRIES = 3
_PASS2_MAX_TOKENS = 64000


# ============================================================
# Public API
# ============================================================
def generate_pass2(
    spec: ScenarioSpec,
    pass1_output: Pass1Output,
    *,
    intermediates_dir: Path | None = None,
) -> tuple[Pass2Output, list[CorrelationPair]]:
    """Run Pass 2 for one scenario.

    Args:
        spec: Loaded scenario spec.
        pass1_output: The Pass 1 result for this scenario.
        intermediates_dir: Where per-call LLM logs go.

    Returns:
        (Pass2Output, list of CorrelationPair).
        For non-correlation scenarios, Pass2Output is byte-equal to Pass 1
        (with pass_=2) and the CorrelationPair list is empty.

    Raises:
        RuntimeError: if Pass 2 LLM call fails or invariance is violated
                      after _MAX_RETRIES.
    """
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    correlations = spec.pass2_correlations or []

    if not correlations:
        # Pass-through case
        print(f"  Pass 2 [{spec.scenario_id}]: no correlations, pass-through")
        pass2 = _passthrough(pass1_output)
        return pass2, []

    print(f"  Pass 2 [{spec.scenario_id}]: {len(correlations)} correlation rule(s), invoking LLM")
    pass2 = _correlation_inject(
        spec=spec,
        pass1_output=pass1_output,
        intermediates_dir=intermediates_dir,
    )

    print(f"  Pass 2 [{spec.scenario_id}]: computing correlation evidence...")
    pairs = _compute_correlation_evidence(spec, pass2)
    return pass2, pairs


def write_pass2_intermediate(output: Pass2Output, intermediates_dir: Path) -> Path:
    """Persist Pass2Output atomically to intermediates/NN/pass2.json."""
    target = checkpoint_path(output.scenario_id, "pass2", intermediates_dir)
    write_pydantic_atomic(target, output)
    return target


def read_pass2_intermediate(scenario_id: str, intermediates_dir: Path) -> Pass2Output:
    """Load a previously-written Pass2Output."""
    target = checkpoint_path(scenario_id, "pass2", intermediates_dir)
    if not target.exists():
        raise FileNotFoundError(
            f"Pass 2 intermediate not found: {target}. Run pass2 for {scenario_id} first."
        )
    with target.open(encoding="utf-8") as f:
        data = json.load(f)
    return Pass2Output.model_validate(data)


# ============================================================
# Pass-through case
# ============================================================
def _passthrough(pass1_output: Pass1Output) -> Pass2Output:
    """Convert Pass1Output → Pass2Output with no telemetry changes."""
    return Pass2Output(
        scenario_id=pass1_output.scenario_id,
        Compute_Metrics=pass1_output.Compute_Metrics,
        Database_Metrics=pass1_output.Database_Metrics,
        Cache_Metrics=pass1_output.Cache_Metrics,
        Network_Metrics=pass1_output.Network_Metrics,
    )


# ============================================================
# Correlation injection case
# ============================================================
def _correlation_inject(
    *,
    spec: ScenarioSpec,
    pass1_output: Pass1Output,
    intermediates_dir: Path,
) -> Pass2Output:
    """Call LLM with Pass 1 JSON + correlation rules. Validate invariance."""
    client = LLMClient(model=PASS2_MODEL, max_tokens=_PASS2_MAX_TOKENS)

    # Affected tiers (those mentioned in any correlation effect)
    affected = _affected_tiers(spec)

    substitutions = _build_substitutions(spec, pass1_output)
    log_path = intermediates_dir / spec.scenario_id / "pass2_llm_log.json"

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.call(
                prompt_path=PASS2_PROMPT_PATH,
                substitutions=substitutions,
                log_path=log_path,
                metadata={
                    "scenario_id": spec.scenario_id,
                    "phase": "pass2",
                    "attempt": attempt,
                },
            )
            data = json.loads(response)
            pass2 = _parse_and_validate_pass2(data, spec.scenario_id)
            _enforce_invariance(pass1_output, pass2, affected_tiers=affected)
            return pass2
        except (json.JSONDecodeError, ValidationError, ValueError, AssertionError) as e:
            last_error = e
            print(f"    Pass 2 attempt {attempt}/{_MAX_RETRIES} failed: {type(e).__name__}: {e}")

    raise RuntimeError(
        f"Pass 2 failed for scenario {spec.scenario_id} after {_MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _parse_and_validate_pass2(data: dict, scenario_id: str) -> Pass2Output:
    """Validate top-level shape + per-record types. Raises ValidationError on failure."""
    if not isinstance(data, dict):
        raise ValueError(f"Pass 2 response must be a JSON object, got {type(data).__name__}")
    for tier, key in _TIER_KEYS.items():
        arr = data.get(key)
        if arr is None:
            raise ValueError(f"Pass 2 response missing key {key}")
        if not isinstance(arr, list):
            raise ValueError(f"Pass 2 response {key} must be a list")
        model_cls = _TIER_MODELS[tier]
        for i, rec in enumerate(arr):
            try:
                model_cls.model_validate(rec)
            except ValidationError as e:
                raise ValueError(f"{key}[{i}] failed validation: {e}") from e
    return Pass2Output.model_validate(
        {
            "scenario_id": scenario_id,
            **{key: data[key] for key in _TIER_KEYS.values()},
        }
    )


def _enforce_invariance(
    pass1: Pass1Output,
    pass2: Pass2Output,
    *,
    affected_tiers: set[str],
) -> None:
    """Assert Pass 2 preserves Pass 1 exactly for unaffected tiers.

    The invariance contract per generation-methodology.md §3:
      - Tiers NOT mentioned as correlation effect targets: Pass 2 array
        must equal Pass 1 array bit-exactly.
      - Tiers that ARE effect targets: timestamps unchanged, no fields
        added/removed. (Per-record value changes are allowed only within
        the trigger windows; this stricter check is done by qa_validator.)

    Raises:
        AssertionError with a diagnostic message on any violation.
    """
    for tier, key in _TIER_KEYS.items():
        p1_arr = getattr(pass1, key)
        p2_arr = getattr(pass2, key)
        if len(p1_arr) != len(p2_arr):
            raise AssertionError(
                f"Pass 2 invariance violation: {key} record count changed "
                f"({len(p1_arr)} → {len(p2_arr)})"
            )
        if tier in affected_tiers:
            # Affected tier — check structural integrity (timestamps + field names),
            # but allow value changes. Detailed timing/magnitude checks happen in QA.
            for i, (p1_rec, p2_rec) in enumerate(zip(p1_arr, p2_arr)):
                if p1_rec.get("timestamp") != p2_rec.get("timestamp"):
                    raise AssertionError(
                        f"Pass 2 invariance violation: {key}[{i}] timestamp changed "
                        f"({p1_rec.get('timestamp')} → {p2_rec.get('timestamp')})"
                    )
                if set(p1_rec.keys()) != set(p2_rec.keys()):
                    raise AssertionError(
                        f"Pass 2 invariance violation: {key}[{i}] field set changed "
                        f"({set(p1_rec.keys())} → {set(p2_rec.keys())})"
                    )
        else:
            # Unaffected tier — must be byte-for-byte identical
            for i, (p1_rec, p2_rec) in enumerate(zip(p1_arr, p2_arr)):
                if p1_rec != p2_rec:
                    raise AssertionError(
                        f"Pass 2 invariance violation: unaffected tier {key}[{i}] "
                        f"changed from Pass 1.\nPass 1: {p1_rec}\nPass 2: {p2_rec}"
                    )


def _affected_tiers(spec: ScenarioSpec) -> set[str]:
    """Set of tier names that appear as `effect.tier` in any correlation rule."""
    tiers: set[str] = set()
    for rule in spec.pass2_correlations or []:
        for effect in rule.get("effect", []):
            t = effect.get("tier")
            if t:
                tiers.add(t)
    return tiers


# ============================================================
# Correlation evidence — computed from data, not asked from LLM
# ============================================================
def _compute_correlation_evidence(
    spec: ScenarioSpec, pass2: Pass2Output,
) -> list[CorrelationPair]:
    """For each correlation rule, compute Pearson + lag + alignment from data."""
    pairs: list[CorrelationPair] = []
    for rule in spec.pass2_correlations or []:
        trigger_tier = rule.get("trigger", {}).get("tier")
        trigger_metric = rule.get("trigger", {}).get("metric")
        if not trigger_tier or not trigger_metric:
            continue
        for effect in rule.get("effect", []):
            effect_tier = effect.get("tier")
            effect_metric = effect.get("metric")
            if not effect_tier or not effect_metric:
                continue
            try:
                pair = _build_correlation_pair(
                    pass2=pass2,
                    tier_a=trigger_tier,
                    metric_a=trigger_metric,
                    tier_b=effect_tier,
                    metric_b=effect_metric,
                    description=f"{rule.get('pattern', 'correlation')}",
                )
                pairs.append(pair)
            except (KeyError, ValueError) as e:
                print(f"    Skipping correlation pair {trigger_tier}.{trigger_metric}"
                      f" → {effect_tier}.{effect_metric}: {e}")
    return pairs


def _build_correlation_pair(
    *,
    pass2: Pass2Output,
    tier_a: str,
    metric_a: str,
    tier_b: str,
    metric_b: str,
    description: str,
) -> CorrelationPair:
    """Extract two time series, compute Pearson + simple lag + alignment."""
    series_a = _extract_series(pass2, tier_a, metric_a)
    series_b = _extract_series(pass2, tier_b, metric_b)
    if len(series_a) != len(series_b) or not series_a:
        raise ValueError(f"Series length mismatch or empty: {len(series_a)} vs {len(series_b)}")

    coefficient = _pearson(series_a, series_b)
    alignment = _alignment_score(series_a, series_b)
    return CorrelationPair(
        tier_a=TierName(tier_a),
        tier_b=TierName(tier_b),
        metric_a=metric_a,
        metric_b=metric_b,
        coefficient=round(coefficient, 3),
        lag_minutes=0,                                  # spec rules use "same 15-min window"
        alignment_score=round(alignment, 3),
        description=description,
    )


def _extract_series(pass2: Pass2Output, tier: str, metric: str) -> list[float]:
    key = _TIER_KEYS[tier]
    arr = getattr(pass2, key)
    return [float(r[metric]) for r in arr if metric in r and r[metric] is not None]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_x * den_y)))


def _alignment_score(xs: list[float], ys: list[float]) -> float:
    """Proportion of intervals where both series' z-scores moved same direction.

    A rough alignment metric: did both metrics deviate from their respective
    means in the same direction at each timestep?
    """
    n = len(xs)
    if n == 0:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    same_direction = sum(
        1 for x, y in zip(xs, ys)
        if (x >= mean_x) == (y >= mean_y)
    )
    return same_direction / n


# ============================================================
# Substitution builder for the Pass 2 prompt
# ============================================================
def _build_substitutions(spec: ScenarioSpec, pass1: Pass1Output) -> dict[str, object]:
    """Build the substitutions dict for the Pass 2 prompt template."""
    import yaml
    pass1_json_str = pass1.model_dump_json(indent=2)
    correlations_block = yaml.dump(
        {"pass2_correlations": spec.pass2_correlations},
        default_flow_style=False, sort_keys=False,
    )
    baselines_block = yaml.dump(
        {"pass1_metric_ranges": spec.pass1_metrics},
        default_flow_style=False, sort_keys=False,
    )
    return {
        "scenario_id": spec.scenario_id,
        "scenario_name": spec.scenario_name,
        "scenario_type": spec.scenario_type,
        "pass1_json": pass1_json_str,
        "pass2_correlations_block": correlations_block,
        "pass1_baseline_summary": baselines_block,
    }
