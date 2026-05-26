"""Pass 2 rule grammar + work-plan types.

These types are the structured form of `spec.pass2_correlations` after the
window planner (Phase 2A) has parsed them. They isolate the rule grammar
from the YAML so downstream code (planner, agent, merger) never re-parses
the spec.

Design notes
============

The spec YAML uses prose-ish adjustment descriptions like::

    adjustment: "+180 to +250 ms"
    adjustment: "3x baseline (from 40-70 baseline to 130-210 during ...)"
    adjustment: "no adjustment"
    adjustment: "co-rises +120 to +180 ms"

The planner parses these into a typed `AdjustmentSpec` so the agent and
validator don't have to do string parsing under load. See `pass2_planner._parse_adjustment`.

A `WorkItem` is the unit of work for the agent loop in Phase 2B: one
contiguous trigger event (possibly spanning multiple 15-min windows after
merging) for one rule, with all the records the LLM needs to read and the
positions it's allowed to modify.

Pattern verification (G2: "must hold on at least 11 of 14 days") is enforced
*before* the work plan is built. If Pass 1 can't satisfy a rule's pattern,
the planner raises `Pass2PlanInfeasible` with a clear remediation message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


# ============================================================
# Adjustment grammar
# ============================================================
AdjustmentMode = Literal["additive", "multiplicative", "none"]


@dataclass(frozen=True)
class AdjustmentSpec:
    """Typed form of a rule's adjustment description.

    Examples:
      "+180 to +250 ms"        -> mode="additive", lo=180.0, hi=250.0, units="ms"
      "-0.04 to -0.08"         -> mode="additive", lo=-0.08, hi=-0.04, units=""
      "3x baseline (40-70...)" -> mode="multiplicative", factor=3.0,
                                  baseline_lo=40.0, baseline_hi=70.0,
                                  target_lo=130.0, target_hi=210.0
      "no adjustment"          -> mode="none"
      "co-rises +120 to +180"  -> mode="additive", lo=120.0, hi=180.0
                                  (the "co-rises" hint is captured in raw_text)
    """

    mode: AdjustmentMode
    raw_text: str
    # Additive fields (mode == "additive")
    lo: float | None = None              # min adjustment to add to Pass 1 baseline
    hi: float | None = None              # max adjustment
    units: str = ""                      # "ms", "Mbps", "" for ratios
    # Multiplicative fields (mode == "multiplicative")
    factor: float | None = None          # e.g., 3.0 for "3x baseline"
    baseline_lo: float | None = None     # Pass 1 baseline range low (from spec text)
    baseline_hi: float | None = None     # Pass 1 baseline range high
    target_lo: float | None = None       # Resulting target value low
    target_hi: float | None = None       # Resulting target value high

    def applies_to_value(self, pass1_value: float) -> tuple[float, float]:
        """Return the (lo, hi) bounds the LLM's emitted value must fall within.

        For additive: bounds = (pass1_value + lo, pass1_value + hi).
        For multiplicative: bounds = (target_lo, target_hi) — these come
            from the spec's stated absolute target range and do NOT depend on
            the per-record Pass 1 value.
        For none: bounds = (pass1_value, pass1_value).
        """
        if self.mode == "none":
            return (pass1_value, pass1_value)
        if self.mode == "multiplicative":
            assert self.target_lo is not None and self.target_hi is not None
            return (self.target_lo, self.target_hi)
        # additive
        assert self.lo is not None and self.hi is not None
        return (pass1_value + self.lo, pass1_value + self.hi)


# ============================================================
# Timing grammar
# ============================================================
TimingMode = Literal["same_window", "within_n_records"]


@dataclass(frozen=True)
class TimingSpec:
    """When the effect lands relative to the trigger record."""

    mode: TimingMode
    raw_text: str
    lag_records_lo: int = 0              # 0 for same_window
    lag_records_hi: int = 0              # >0 for "within 15-30 minutes" → 1..2


# ============================================================
# Parsed effect (one element of `rule.effect`)
# ============================================================
@dataclass(frozen=True)
class EffectSpec:
    tier: str                            # "compute" | "database" | "cache" | "network"
    metric: str                          # e.g. "db_query_p95_latency_ms"
    adjustment: AdjustmentSpec
    timing: TimingSpec


# ============================================================
# Parsed trigger (rule.trigger)
# ============================================================
@dataclass(frozen=True)
class TriggerSpec:
    tier: str
    metric: str
    condition_raw: str                   # original string, e.g., "value < 0.72"
    condition_op: Literal["<", "<=", ">", ">=", "=="]
    condition_value: float
    # Scope filter parsed from the rule's `pattern` text (G1):
    # If set, only windows whose timestamp matches this scope filter count
    # as trigger windows, even if the numeric condition is satisfied.
    scope_business_hours_only: bool = False
    scope_weekdays_only: bool = False
    scope_weekend_only: bool = False
    scope_peak_windows: bool = False


# ============================================================
# Pattern requirement (rule.pattern)
# ============================================================
@dataclass(frozen=True)
class PatternRequirement:
    """The 'must hold on at least N of M days' verification rule.

    Parsed from prose like:
      "must hold on at least 11 of 14 days during weekday business hours"
      "must hold on all 10 weekday dates during business hours"
      "must hold on all 10 weekday dates during the two daily spike windows"
      "all three tiers simultaneously low across all 14 days"
      "all three tiers rise together with no clear lead-lag"
    """

    raw_text: str
    min_qualifying_days: int             # e.g., 11
    total_days: int                      # e.g., 14
    # Lag-zero requirement (G4 — diagnostic_deferral scenarios)
    require_lag_zero: bool = False
    # Whether this rule is purely for correlation_evidence with no LLM modification (G6)
    evidence_only: bool = False
    notes: str = ""


# ============================================================
# Compiled rule — what the planner emits per spec rule
# ============================================================
@dataclass(frozen=True)
class CompiledRule:
    rule_index: int                      # position in spec.pass2_correlations
    trigger: TriggerSpec
    effects: tuple[EffectSpec, ...]
    pattern: PatternRequirement
    raw_yaml: dict                       # for logging / debugging


# ============================================================
# Work item — one unit handed to the agent loop
# ============================================================
@dataclass(frozen=True)
class WorkItem:
    """One contiguous trigger event for one rule, across all affected tiers.

    A WorkItem may span several consecutive 15-min trigger windows that the
    planner merged together (G5). The agent processes it as a single LLM
    call so the emitted adjustments are smooth across the event.
    """

    work_id: str                         # e.g., "rule0_w0042" — stable across runs
    rule_index: int                      # CompiledRule.rule_index
    # Trigger span (the merged set of consecutive windows that satisfy the condition)
    trigger_start_iso: str               # ISO timestamp of first trigger record
    trigger_end_iso: str                 # ISO timestamp of last trigger record (inclusive)
    trigger_record_indices: tuple[int, ...]  # indices in trigger tier's 1344-record array
    # Effect spans (per effect): may differ from trigger span when timing.lag>0.
    # Indices are into each effect tier's 1344-record array.
    effect_record_indices: dict[str, tuple[int, ...]]  # tier → indices
    # Snapshot of the records the LLM needs to see — Pass 1 values, for context.
    # Provided in compact form (just the values, with their position).
    pass1_trigger_records: tuple[dict, ...]                 # trigger tier records in span
    pass1_effect_records: dict[str, tuple[dict, ...]]       # effect tier → records in span


# ============================================================
# Plan — the full output of Phase 2A
# ============================================================
@dataclass(frozen=True)
class Pass2Plan:
    scenario_id: str
    pass1_sha256: str                    # for chunk invalidation (G9)
    rules: tuple[CompiledRule, ...]
    work_items: tuple[WorkItem, ...]
    # Pre-verified: each rule's pattern is satisfiable from Pass 1's trigger fires.
    pattern_verification: dict[int, "PatternCheckResult"]   # rule_index → result


@dataclass(frozen=True)
class PatternCheckResult:
    rule_index: int
    qualifying_days: int                 # how many distinct days had ≥1 trigger window
    required_days: int                   # from PatternRequirement.min_qualifying_days
    feasible: bool                       # qualifying_days >= required_days
    qualifying_dates: tuple[str, ...]    # for logging


# ============================================================
# Exceptions
# ============================================================
class Pass2PlanInfeasible(Exception):
    """Raised when Pass 1's trigger fires can't satisfy a rule's pattern.

    The message includes the actionable remediation (which rule, current
    vs required qualifying days, suggested Pass 1 spec adjustment).
    """


class Pass2RuleParseError(Exception):
    """Raised when a rule's YAML can't be parsed into the typed grammar."""


class Pass2WindowAgentError(Exception):
    """Raised when an agent loop fails to produce valid output for one window."""


class Pass2CostCeilingExceeded(Exception):
    """Raised when per-scenario cost ceiling is hit. Aborts cleanly with
    checkpoint preserved so resume can continue from where we stopped."""


# ============================================================
# Sentinel for the no-rule case
# ============================================================
@dataclass(frozen=True)
class VerificationResult:
    """Output of the mandatory per-scenario Pass 2 verification call (G10).

    Even scenarios with empty `pass2_correlations` produce a verification
    artifact, so the LLM path is exercised uniformly. The LLM looks at a
    sample of Pass 1 records and confirms plausibility.
    """

    scenario_id: str
    sample_indices: dict[str, tuple[int, ...]]  # tier → sampled record indices
    verdict: Literal["pass", "concern", "fail"]
    concerns: tuple[str, ...]
    raw_response: str
