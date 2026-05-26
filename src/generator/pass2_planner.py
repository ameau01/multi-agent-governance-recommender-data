"""Pass 2 Phase 2A — window planning (no LLM, deterministic).

Inputs:
  - ScenarioSpec (with pass2_correlations YAML rules)
  - Pass1Output (the 1344-record-per-tier baseline)

Outputs:
  - Pass2Plan: compiled rules, work items, per-rule pattern feasibility check.

Responsibilities (mapping to gap analysis):
  G1  Parse rule.pattern scope text → TriggerSpec scope flags
      (business_hours_only, weekdays_only, weekend_only, peak_windows).
  G2  Before producing work items: verify each rule's pattern requirement
      ("must hold on at least N of M days") is satisfiable from Pass 1.
      Raise Pass2PlanInfeasible with actionable message if not.
  G3  Parse multiplicative adjustments ("3x baseline (from X to Y)") as well
      as additive ("+180 to +250 ms"). Both shapes typed in AdjustmentSpec.
  G4  Set PatternRequirement.require_lag_zero=True for diagnostic_deferral
      scenarios (pattern text contains "no clear lead-lag" or "no lead-lag").
  G5  Merge consecutive trigger windows separated by ≤ PASS2_MERGE_GAP_MINUTES
      into a single WorkItem so the LLM emits smooth adjustments.
  G6  Detect "no adjustment" / "co-presence" rules. Mark PatternRequirement
      .evidence_only=True. These rules emit a WorkItem-less plan entry that
      only contributes to correlation_evidence in Phase 2C.
  G7  Overlapping trigger windows from different rules → raise Pass2PlanInfeasible
      (until we have multi-rule scenarios that actually exercise this).

NO LLM CALLS IN THIS MODULE.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from generator.constants import (
    DATA_WINDOW_DAYS,
    DATA_WINDOW_START_UTC,
    INTERVAL_MINUTES,
    PASS2_MERGE_GAP_MINUTES,
)
from generator.checkpoint import sha256_bytes_hex
from generator.pass2_types import (
    AdjustmentSpec,
    CompiledRule,
    EffectSpec,
    Pass2Plan,
    Pass2PlanInfeasible,
    Pass2RuleParseError,
    PatternCheckResult,
    PatternRequirement,
    TimingSpec,
    TriggerSpec,
    WorkItem,
)
from generator.types import Pass1Output, ScenarioSpec


_TIER_KEYS = {
    "compute": "Compute_Metrics",
    "database": "Database_Metrics",
    "cache": "Cache_Metrics",
    "network": "Network_Metrics",
}

_RECORDS_PER_DAY = 96   # 24 * 4

# Weekend dates (matches Pass 1 prompt convention)
_WEEKEND_ISO = {"2026-05-02", "2026-05-03", "2026-05-09", "2026-05-10"}


# ============================================================
# Public entrypoint
# ============================================================
def plan_pass2(
    spec: ScenarioSpec,
    pass1: Pass1Output,
) -> Pass2Plan:
    """Compile spec.pass2_correlations and produce a typed work plan.

    Raises:
        Pass2RuleParseError: if a rule's YAML cannot be parsed.
        Pass2PlanInfeasible: if a rule's pattern can't be satisfied by Pass 1
            (with an actionable message naming the rule, the qualifying days
            found, and the required days).
    """
    raw_rules = spec.pass2_correlations or []
    compiled = tuple(_compile_rule(i, r) for i, r in enumerate(raw_rules))

    # G2: Verify pattern feasibility BEFORE building work items.
    pattern_results: dict[int, PatternCheckResult] = {}
    for rule in compiled:
        result = _check_pattern_feasibility(rule, pass1)
        pattern_results[rule.rule_index] = result
        if not result.feasible:
            raise Pass2PlanInfeasible(
                f"Scenario {spec.scenario_id}: rule {rule.rule_index} "
                f"(trigger={rule.trigger.tier}.{rule.trigger.metric} "
                f"{rule.trigger.condition_op} {rule.trigger.condition_value}) "
                f"has trigger fires on {result.qualifying_days} day(s) but the "
                f"pattern requires at least {result.required_days}. "
                f"Qualifying dates: {list(result.qualifying_dates)}. "
                f"Remediation: regenerate Pass 1 with a tighter "
                f"{rule.trigger.metric} range (or wider drop-pattern) so the "
                f"trigger condition fires on ≥{result.required_days} days."
            )

    # G6: Skip work item generation for evidence_only rules.
    # G7: Collect all (rule_index, record_indices) spans to detect overlap.
    all_spans: list[tuple[int, str, set[int]]] = []  # (rule_idx, trigger_tier, indices)
    work_items: list[WorkItem] = []
    for rule in compiled:
        if rule.pattern.evidence_only:
            continue
        items = _build_work_items_for_rule(rule, pass1)
        for item in items:
            all_spans.append(
                (rule.rule_index, rule.trigger.tier, set(item.trigger_record_indices))
            )
        work_items.extend(items)

    _check_no_overlap_between_rules(all_spans, spec.scenario_id)

    pass1_bytes = pass1.model_dump_json().encode()
    pass1_sha = sha256_bytes_hex(pass1_bytes)

    return Pass2Plan(
        scenario_id=spec.scenario_id,
        pass1_sha256=pass1_sha,
        rules=compiled,
        work_items=tuple(work_items),
        pattern_verification=pattern_results,
    )


# ============================================================
# Rule compilation — YAML dict → CompiledRule
# ============================================================
def _compile_rule(rule_index: int, raw: dict) -> CompiledRule:
    """Parse one entry of `pass2_correlations` into typed form."""
    if not isinstance(raw, dict):
        raise Pass2RuleParseError(
            f"Rule {rule_index}: expected dict, got {type(raw).__name__}"
        )

    pattern_text = raw.get("pattern", "")
    notes_text = raw.get("notes", "")
    trigger = _parse_trigger(raw.get("trigger", {}), pattern_text)
    effects_raw = raw.get("effect", [])
    if not isinstance(effects_raw, list):
        raise Pass2RuleParseError(
            f"Rule {rule_index}: 'effect' must be a list, got "
            f"{type(effects_raw).__name__}"
        )

    effects = tuple(_parse_effect(rule_index, i, e) for i, e in enumerate(effects_raw))
    pattern = _parse_pattern(pattern_text, notes_text, effects)

    return CompiledRule(
        rule_index=rule_index,
        trigger=trigger,
        effects=effects,
        pattern=pattern,
        raw_yaml=raw,
    )


# ----- trigger -----
_COND_RE = re.compile(
    r"\s*value\s*(<=|>=|==|<|>)\s*([0-9.+\-eE]+)\s*",
)


def _parse_trigger(raw: dict, pattern_text: str) -> TriggerSpec:
    tier = str(raw.get("tier", "")).strip()
    metric = str(raw.get("metric", "")).strip()
    cond_raw = str(raw.get("condition", "")).strip()
    if not tier or not metric:
        raise Pass2RuleParseError(
            f"Trigger missing tier or metric: {raw!r}"
        )

    # Condition may be "value < 0.72" or "value > 380 during business hours"
    # We strip prose suffixes after the numeric for op+value parsing.
    cond_core = cond_raw.split(" during ")[0].split(" on ")[0].strip()
    m = _COND_RE.match(cond_core)
    if not m:
        raise Pass2RuleParseError(
            f"Trigger condition not parseable: {cond_raw!r} "
            f"(expected 'value <op> <number>')"
        )
    op = m.group(1)
    value = float(m.group(2))

    scope_text = (cond_raw + " " + pattern_text).lower()
    return TriggerSpec(
        tier=tier,
        metric=metric,
        condition_raw=cond_raw,
        condition_op=op,
        condition_value=value,
        scope_business_hours_only=("business hours" in scope_text),
        scope_weekdays_only=(
            "weekday" in scope_text
            and "weekend" not in scope_text
        ),
        scope_weekend_only=("weekend" in scope_text and "weekday" not in scope_text),
        scope_peak_windows=(
            "peak window" in scope_text
            or "peak hours" in scope_text
            or "spike window" in scope_text
            or "daily spike" in scope_text
        ),
    )


# ----- effect -----
def _parse_effect(rule_index: int, effect_index: int, raw: dict) -> EffectSpec:
    tier = str(raw.get("tier", "")).strip()
    metric = str(raw.get("metric", "")).strip()
    adj_text = str(raw.get("adjustment", "")).strip()
    timing_text = str(raw.get("timing", "")).strip()
    if not tier or not metric or not adj_text or not timing_text:
        raise Pass2RuleParseError(
            f"Rule {rule_index} effect {effect_index}: missing "
            f"tier/metric/adjustment/timing in {raw!r}"
        )
    adjustment = _parse_adjustment(adj_text)
    timing = _parse_timing(timing_text)
    return EffectSpec(tier=tier, metric=metric, adjustment=adjustment, timing=timing)


# ----- adjustment grammar (G3) -----
_ADDITIVE_RE = re.compile(
    r"(?:co-rises\s+)?"
    r"([+-][0-9.]+)\s*(?:to)?\s*([+-][0-9.]+)?\s*([A-Za-z]+)?",
)
_MULT_RE = re.compile(
    r"([0-9.]+)x\s+baseline\s*\(\s*from\s*([0-9.]+)\s*-\s*([0-9.]+)\s+baseline"
    r"\s+to\s+([0-9.]+)\s*-\s*([0-9.]+)",
)


def _parse_adjustment(text: str) -> AdjustmentSpec:
    text_norm = text.strip().lower()

    # G6: "no adjustment"
    if text_norm in ("no adjustment", "none", ""):
        return AdjustmentSpec(mode="none", raw_text=text)

    # G3: Multiplicative ("3x baseline (from 40-70 baseline to 130-210 during ...)")
    m = _MULT_RE.search(text_norm)
    if m:
        return AdjustmentSpec(
            mode="multiplicative",
            raw_text=text,
            factor=float(m.group(1)),
            baseline_lo=float(m.group(2)),
            baseline_hi=float(m.group(3)),
            target_lo=float(m.group(4)),
            target_hi=float(m.group(5)),
        )

    # Additive ("+180 to +250 ms", "-0.04 to -0.08", "co-rises +60 to +90 ms")
    m = _ADDITIVE_RE.search(text)
    if m:
        lo_str = m.group(1)
        hi_str = m.group(2) or m.group(1)
        units = (m.group(3) or "").strip()
        lo = float(lo_str)
        hi = float(hi_str)
        if lo > hi:
            lo, hi = hi, lo
        return AdjustmentSpec(
            mode="additive",
            raw_text=text,
            lo=lo,
            hi=hi,
            units=units,
        )

    raise Pass2RuleParseError(
        f"Adjustment not parseable: {text!r}. "
        f"Recognized: '+N to +M [units]' | '-N to -M' | 'NxM baseline (from A-B to C-D)' | 'no adjustment'"
    )


# ----- timing -----
def _parse_timing(text: str) -> TimingSpec:
    t = text.strip().lower()
    if "same 15-min window" in t or "same window" in t or t == "":
        return TimingSpec(mode="same_window", raw_text=text)
    # "within 15-30 minutes" → 1..2 record lag (15 min per record)
    m = re.search(r"within\s+([0-9]+)\s*-\s*([0-9]+)\s*minutes?", t)
    if m:
        lo_min = int(m.group(1))
        hi_min = int(m.group(2))
        return TimingSpec(
            mode="within_n_records",
            raw_text=text,
            lag_records_lo=max(1, lo_min // INTERVAL_MINUTES),
            lag_records_hi=max(1, hi_min // INTERVAL_MINUTES),
        )
    # Unknown timing: treat as same_window with a warning baked in raw_text
    return TimingSpec(mode="same_window", raw_text=text)


# ----- pattern requirement (G4, G6) -----
def _parse_pattern(
    pattern_text: str, notes_text: str, effects: tuple[EffectSpec, ...],
) -> PatternRequirement:
    text = (pattern_text + " " + notes_text).lower()

    # G6: evidence-only if all effects have adjustment mode "none"
    evidence_only = bool(effects) and all(e.adjustment.mode == "none" for e in effects)

    # G4: lag-zero requirement for diagnostic_deferral signatures
    require_lag_zero = (
        "no clear lead-lag" in text
        or "no lead-lag" in text
        or "simultaneously" in text
        or "rise together" in text
    )

    total_days = DATA_WINDOW_DAYS  # 14
    min_qualifying = total_days     # safe default; refine via regex below

    # "at least N of M days"
    m = re.search(r"at least\s+(\d+)\s+of\s+(\d+)\s+days?", text)
    if m:
        min_qualifying = int(m.group(1))
        total_days = int(m.group(2))
    else:
        m = re.search(r"all\s+(\d+)\s+weekday\s+dates?", text)
        if m:
            min_qualifying = int(m.group(1))
        else:
            m = re.search(r"across all\s+(\d+)\s+days?", text)
            if m:
                min_qualifying = int(m.group(1))

    return PatternRequirement(
        raw_text=pattern_text,
        min_qualifying_days=min_qualifying,
        total_days=total_days,
        require_lag_zero=require_lag_zero,
        evidence_only=evidence_only,
        notes=notes_text,
    )


# ============================================================
# Trigger detection (G1: scope filter applied)
# ============================================================
def _trigger_record_indices(
    rule: CompiledRule, pass1: Pass1Output,
) -> list[int]:
    """Indices in the trigger tier's array where the trigger fires AND
    the scope filter is satisfied.
    """
    arr = _tier_records(pass1, rule.trigger.tier)
    metric = rule.trigger.metric
    op = rule.trigger.condition_op
    threshold = rule.trigger.condition_value
    indices: list[int] = []
    for i, rec in enumerate(arr):
        val = rec.get(metric)
        if not isinstance(val, (int, float)):
            continue
        if not _condition_satisfied(val, op, threshold):
            continue
        # G1: scope filter
        if not _record_in_scope(rec, rule.trigger):
            continue
        indices.append(i)
    return indices


def _condition_satisfied(val: float, op: str, threshold: float) -> bool:
    if op == "<":   return val < threshold
    if op == "<=":  return val <= threshold
    if op == ">":   return val > threshold
    if op == ">=":  return val >= threshold
    if op == "==":  return val == threshold
    raise ValueError(f"Unknown op {op!r}")


def _record_in_scope(rec: dict, trigger: TriggerSpec) -> bool:
    """G1 scope filter — record's timestamp must match the rule's scope clauses."""
    ts_iso = rec.get("timestamp", "")
    if not ts_iso:
        return False
    date_iso = ts_iso[:10]
    is_weekend = date_iso in _WEEKEND_ISO

    if trigger.scope_weekdays_only and is_weekend:
        return False
    if trigger.scope_weekend_only and not is_weekend:
        return False
    if trigger.scope_business_hours_only:
        hour = int(ts_iso[11:13])
        if not (9 <= hour < 18):
            return False
    # scope_peak_windows: defer to the numeric trigger condition itself —
    # the trigger threshold is set so it fires only during peak periods.
    # Adding additional time-window filtering here would double-count.
    return True


# ============================================================
# G2 pattern feasibility check
# ============================================================
def _check_pattern_feasibility(
    rule: CompiledRule, pass1: Pass1Output,
) -> PatternCheckResult:
    if rule.pattern.evidence_only:
        # Evidence-only rules don't need trigger fires; mark as trivially feasible.
        return PatternCheckResult(
            rule_index=rule.rule_index,
            qualifying_days=rule.pattern.min_qualifying_days,
            required_days=rule.pattern.min_qualifying_days,
            feasible=True,
            qualifying_dates=(),
        )

    indices = _trigger_record_indices(rule, pass1)
    arr = _tier_records(pass1, rule.trigger.tier)
    qualifying_dates = sorted({arr[i]["timestamp"][:10] for i in indices})
    qualifying_days = len(qualifying_dates)
    required = rule.pattern.min_qualifying_days
    return PatternCheckResult(
        rule_index=rule.rule_index,
        qualifying_days=qualifying_days,
        required_days=required,
        feasible=qualifying_days >= required,
        qualifying_dates=tuple(qualifying_dates),
    )


# ============================================================
# Work item construction (G5: merge consecutive windows)
# ============================================================
def _build_work_items_for_rule(
    rule: CompiledRule, pass1: Pass1Output,
) -> list[WorkItem]:
    indices = _trigger_record_indices(rule, pass1)
    if not indices:
        return []

    # G5: Merge consecutive trigger indices into spans. Indices separated by
    # ≤ (PASS2_MERGE_GAP_MINUTES / INTERVAL_MINUTES) records collapse into one span.
    max_gap = max(1, PASS2_MERGE_GAP_MINUTES // INTERVAL_MINUTES)
    spans: list[list[int]] = []
    current: list[int] = [indices[0]]
    for idx in indices[1:]:
        if idx - current[-1] <= max_gap:
            current.append(idx)
        else:
            spans.append(current)
            current = [idx]
    spans.append(current)

    trigger_arr = _tier_records(pass1, rule.trigger.tier)
    work_items: list[WorkItem] = []
    for span_n, span in enumerate(spans):
        first_idx = span[0]
        last_idx = span[-1]
        trigger_start_iso = trigger_arr[first_idx]["timestamp"]
        trigger_end_iso = trigger_arr[last_idx]["timestamp"]

        trigger_snapshot = tuple(trigger_arr[i] for i in span)

        # For each effect, compute affected record indices and snapshot.
        effect_indices: dict[str, tuple[int, ...]] = {}
        effect_snapshots: dict[str, tuple[dict, ...]] = {}
        for effect in rule.effects:
            eff_indices = _effect_indices_for_span(span, effect.timing)
            effect_arr = _tier_records(pass1, effect.tier)
            # Clip to valid range [0, len(effect_arr))
            eff_indices = tuple(i for i in eff_indices if 0 <= i < len(effect_arr))
            # If multiple effects target the same tier, merge their indices
            # (the LLM will emit one record per index covering all effects).
            existing = effect_indices.get(effect.tier, ())
            merged = tuple(sorted(set(existing) | set(eff_indices)))
            effect_indices[effect.tier] = merged
            effect_snapshots[effect.tier] = tuple(effect_arr[i] for i in merged)

        work_id = f"rule{rule.rule_index}_w{span_n:04d}"
        work_items.append(
            WorkItem(
                work_id=work_id,
                rule_index=rule.rule_index,
                trigger_start_iso=trigger_start_iso,
                trigger_end_iso=trigger_end_iso,
                trigger_record_indices=tuple(span),
                effect_record_indices=effect_indices,
                pass1_trigger_records=trigger_snapshot,
                pass1_effect_records=effect_snapshots,
            )
        )
    return work_items


def _effect_indices_for_span(span: list[int], timing: TimingSpec) -> tuple[int, ...]:
    """Given trigger span [t0, t1, ...], compute the record indices the effect
    metric should land on for each effect tier."""
    if timing.mode == "same_window":
        return tuple(span)
    # within_n_records: each trigger index propagates effects to [trig+lag_lo .. trig+lag_hi]
    out: set[int] = set()
    for t_idx in span:
        for lag in range(timing.lag_records_lo, timing.lag_records_hi + 1):
            out.add(t_idx + lag)
    return tuple(sorted(out))


# ============================================================
# G7 overlap detection
# ============================================================
def _check_no_overlap_between_rules(
    all_spans: list[tuple[int, str, set[int]]],
    scenario_id: str,
) -> None:
    """Two work items from DIFFERENT rules that touch the same trigger-tier
    record index are forbidden until we have a defined merge semantics."""
    seen: dict[tuple[str, int], int] = {}
    for rule_idx, tier, indices in all_spans:
        for idx in indices:
            key = (tier, idx)
            if key in seen and seen[key] != rule_idx:
                raise Pass2PlanInfeasible(
                    f"Scenario {scenario_id}: rules {seen[key]} and {rule_idx} "
                    f"both target trigger {tier} record index {idx}. "
                    f"Multi-rule overlap is not currently supported. "
                    f"Either disambiguate scope or extend the planner to "
                    f"define a merge semantics (e.g., sequential application)."
                )
            seen[key] = rule_idx


# ============================================================
# Helpers
# ============================================================
def _tier_records(pass1: Pass1Output, tier: str) -> list[dict]:
    """Return the tier's record list as plain dicts."""
    key = _TIER_KEYS[tier]
    arr = getattr(pass1, key)
    # Pass1Output stores tier records as list[dict]; if pydantic models,
    # convert. Defensive either way.
    if arr and hasattr(arr[0], "model_dump"):
        return [r.model_dump(mode="json") for r in arr]
    return list(arr)


# ============================================================
# Plan persistence (atomic write for debugging / smoke testing)
# ============================================================
def write_plan(plan: Pass2Plan, path: Path) -> None:
    """Atomic write of a Pass2Plan to JSON for inspection.

    The persisted form is NOT used for resume — that's the per-window stamps.
    This file is purely a diagnostic snapshot of what the planner decided.
    """
    from generator.checkpoint import write_json_atomic
    payload = {
        "scenario_id": plan.scenario_id,
        "pass1_sha256": plan.pass1_sha256,
        "rules": [
            {
                "rule_index": r.rule_index,
                "trigger": {
                    "tier": r.trigger.tier,
                    "metric": r.trigger.metric,
                    "condition_raw": r.trigger.condition_raw,
                    "condition_op": r.trigger.condition_op,
                    "condition_value": r.trigger.condition_value,
                    "scope_business_hours_only": r.trigger.scope_business_hours_only,
                    "scope_weekdays_only": r.trigger.scope_weekdays_only,
                    "scope_weekend_only": r.trigger.scope_weekend_only,
                    "scope_peak_windows": r.trigger.scope_peak_windows,
                },
                "effects": [
                    {
                        "tier": e.tier,
                        "metric": e.metric,
                        "adjustment_mode": e.adjustment.mode,
                        "adjustment_raw": e.adjustment.raw_text,
                        "timing_mode": e.timing.mode,
                        "timing_raw": e.timing.raw_text,
                    }
                    for e in r.effects
                ],
                "pattern": {
                    "raw": r.pattern.raw_text,
                    "min_qualifying_days": r.pattern.min_qualifying_days,
                    "total_days": r.pattern.total_days,
                    "require_lag_zero": r.pattern.require_lag_zero,
                    "evidence_only": r.pattern.evidence_only,
                    "notes": r.pattern.notes,
                },
            }
            for r in plan.rules
        ],
        "pattern_verification": {
            str(k): {
                "qualifying_days": v.qualifying_days,
                "required_days": v.required_days,
                "feasible": v.feasible,
                "qualifying_dates": list(v.qualifying_dates),
            }
            for k, v in plan.pattern_verification.items()
        },
        "work_items": [
            {
                "work_id": w.work_id,
                "rule_index": w.rule_index,
                "trigger_start_iso": w.trigger_start_iso,
                "trigger_end_iso": w.trigger_end_iso,
                "trigger_record_indices": list(w.trigger_record_indices),
                "effect_record_indices": {
                    tier: list(idxs)
                    for tier, idxs in w.effect_record_indices.items()
                },
            }
            for w in plan.work_items
        ],
    }
    write_json_atomic(path, payload, indent=2)
