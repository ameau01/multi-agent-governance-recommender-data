"""Pass 2 Phase 2B — per-window LLM agent loop with multi-turn feedback.

For each WorkItem in a Pass2Plan, this module runs a bounded multi-turn
conversation with the model:

    Turn 1: render prompt for this single window, send to LLM.
    Turn N: if validation finds violations, send a focused user message
            naming each violating (tier, index, field) and the constraint
            it violated. Ask for ONLY the corrected records.
    Stop:   when validation passes, or PASS2_AGENT_MAX_TURNS is exceeded.

Validation is strict — see _validate_response below. The python validator,
not the LLM, decides what's correct:
  - JSON parses; top-level has "modified_records" mapping each effect tier
    to a list of {index, record} entries.
  - Every index appears in the work item's effect_record_indices for its tier.
  - Every record has all of Pass 1's fields (same schema).
  - Modified metric values fall inside the adjustment bounds derived from
    the rule (additive: pass1+lo .. pass1+hi; multiplicative: target_lo .. target_hi).
  - Unmodified fields equal Pass 1 EXACTLY (no drift).
  - Timestamps are NEVER modified.

Provenance: every successful window writes (a) the modified records as a
JSON checkpoint, (b) a stamp sidecar with (pass1_sha, rule_index,
prompt_sha, trigger_start_iso, trigger_end_iso), (c) a per-window LLM log
that captures every turn of the conversation. Resume across runs is
controlled by `checkpoint.window_checkpoint_valid`.

Cost ceiling (PASS2_SCENARIO_MAX_COST_USD) is tracked across all windows in
one scenario. If exceeded mid-loop, the agent raises
Pass2CostCeilingExceeded — pre-existing window checkpoints remain valid,
so a subsequent run resumes from the next window.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import anthropic

from generator.checkpoint import (
    WindowStamp,
    sha256_bytes_hex,
    sha256_file_hex,
    window_checkpoint_path,
    window_checkpoint_valid,
    window_llm_log_path,
    window_stamp_path,
    write_json_atomic,
    write_window_stamp,
)
from generator.constants import (
    PASS2_AGENT_MAX_TURNS,
    PASS2_MODEL,
    PASS2_SCENARIO_MAX_COST_USD,
    PASS2_TEMPERATURE,
    PASS2_WINDOW_MAX_TOKENS,
    SDK_MAX_RETRIES,
)
from generator.pass2_types import (
    AdjustmentSpec,
    CompiledRule,
    EffectSpec,
    Pass2CostCeilingExceeded,
    Pass2WindowAgentError,
    TimingSpec,
    WorkItem,
)


PASS2_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "pass2.txt"

# Approximate per-token pricing for cost tracking (USD per 1M tokens).
# Sonnet 4.6 published rates. Override via env for other models.
_PRICING_INPUT_USD_PER_MTOKEN = float(
    os.getenv("DATAGEN_PASS2_PRICE_INPUT_USD_PER_MTOKEN", "3.0")
)
_PRICING_OUTPUT_USD_PER_MTOKEN = float(
    os.getenv("DATAGEN_PASS2_PRICE_OUTPUT_USD_PER_MTOKEN", "15.0")
)
_PRICING_CACHE_WRITE_USD_PER_MTOKEN = float(
    os.getenv("DATAGEN_PASS2_PRICE_CACHE_WRITE_USD_PER_MTOKEN", "3.75")
)
_PRICING_CACHE_READ_USD_PER_MTOKEN = float(
    os.getenv("DATAGEN_PASS2_PRICE_CACHE_READ_USD_PER_MTOKEN", "0.30")
)


def _log(msg: str = "") -> None:
    """Timestamped stdout, always flushed."""
    if not msg.strip():
        print(msg, flush=True)
        return
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================
# Cost tracking
# ============================================================
class CostMeter:
    """Accumulates Anthropic usage and computes USD spent across an agent run."""

    def __init__(self, ceiling_usd: float):
        self.ceiling_usd = ceiling_usd
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0

    def add_usage(self, usage: Any) -> None:
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_write_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)

    @property
    def total_usd(self) -> float:
        return (
            self.input_tokens * _PRICING_INPUT_USD_PER_MTOKEN / 1_000_000
            + self.output_tokens * _PRICING_OUTPUT_USD_PER_MTOKEN / 1_000_000
            + self.cache_write_tokens * _PRICING_CACHE_WRITE_USD_PER_MTOKEN / 1_000_000
            + self.cache_read_tokens * _PRICING_CACHE_READ_USD_PER_MTOKEN / 1_000_000
        )

    def check_ceiling(self, scenario_id: str) -> None:
        if self.ceiling_usd > 0 and self.total_usd >= self.ceiling_usd:
            raise Pass2CostCeilingExceeded(
                f"Scenario {scenario_id}: Pass 2 cost ceiling "
                f"${self.ceiling_usd:.2f} exceeded "
                f"(current ${self.total_usd:.2f}). "
                f"Existing window checkpoints are preserved — re-run to resume."
            )


# ============================================================
# Anthropic client construction (mirrors llm_client._make_anthropic_client)
# ============================================================
def _make_client() -> "anthropic.Anthropic":
    raw = anthropic.Anthropic(max_retries=SDK_MAX_RETRIES)
    if os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1"):
        from langsmith.wrappers import wrap_anthropic
        return wrap_anthropic(raw)
    return raw


# ============================================================
# Prompt parsing — re-uses the same SYSTEM/USER split as llm_client
# ============================================================
_SECTION_RE = re.compile(r"^(SYSTEM|USER):\s*$", re.MULTILINE)


def _split_prompt(text: str) -> tuple[str, str]:
    matches = list(_SECTION_RE.finditer(text))
    if len(matches) != 2:
        raise ValueError(f"pass2 prompt must have exactly SYSTEM: and USER: markers")
    sys_match, user_match = matches
    system = text[sys_match.end():user_match.start()].strip()
    user = text[user_match.end():].strip()
    return system, user


# ============================================================
# Public entrypoint
# ============================================================
def run_window_agent_loop(
    *,
    scenario_id: str,
    work_item: WorkItem,
    rule: CompiledRule,
    pass1_records_by_tier: dict[str, list[dict]],
    pass1_sha256: str,
    prompt_sha256: str,
    intermediates_dir: Path,
    cost_meter: CostMeter,
) -> dict[str, list[dict]]:
    """Process one WorkItem: run multi-turn LLM with validation feedback.

    Returns:
        dict mapping effect tier name → list of modified records (in the
        order of the work item's effect_record_indices for that tier).

    Raises:
        Pass2WindowAgentError: if validation fails after PASS2_AGENT_MAX_TURNS.
        Pass2CostCeilingExceeded: if cost ceiling is hit mid-loop.
    """
    # Resume short-circuit: if a stamp-matching checkpoint already exists, return it.
    expected_stamp = WindowStamp(
        pass1_sha256=pass1_sha256,
        rule_index=rule.rule_index,
        prompt_sha256=prompt_sha256,
        trigger_start_iso=work_item.trigger_start_iso,
        trigger_end_iso=work_item.trigger_end_iso,
    )
    if window_checkpoint_valid(
        scenario_id, work_item.work_id, expected_stamp, intermediates_dir
    ):
        _log(f"  ↻ {work_item.work_id}: stamp matches, reusing checkpoint")
        cp_path = window_checkpoint_path(scenario_id, work_item.work_id, intermediates_dir)
        return json.loads(cp_path.read_text())

    # Render initial prompt.
    prompt_text = PASS2_PROMPT_PATH.read_text(encoding="utf-8")
    system_text, user_template = _split_prompt(prompt_text)
    user_text = _render_user_prompt(user_template, work_item, rule, pass1_records_by_tier)

    # Multi-turn conversation: each turn appends to `messages`.
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_text}
    ]
    conversation_log: list[dict[str, Any]] = []

    client = _make_client()

    for turn in range(1, PASS2_AGENT_MAX_TURNS + 1):
        cost_meter.check_ceiling(scenario_id)
        _log(
            f"  → {work_item.work_id} turn {turn}/{PASS2_AGENT_MAX_TURNS}: "
            f"calling {PASS2_MODEL} (max_tokens={PASS2_WINDOW_MAX_TOKENS})"
        )
        response_text, usage = _send_one_turn(
            client=client, system=system_text, messages=messages,
        )
        cost_meter.add_usage(usage)
        conversation_log.append({
            "turn": turn,
            "messages_sent": copy.deepcopy(messages),
            "response_text": response_text,
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            },
            "cost_total_usd_after_turn": round(cost_meter.total_usd, 4),
        })

        # Validate; on success, persist + return. On failure, append feedback message.
        try:
            modified = _parse_and_validate_response(
                response_text=response_text,
                work_item=work_item,
                rule=rule,
                pass1_records_by_tier=pass1_records_by_tier,
            )
        except _ValidationFailure as vf:
            feedback = _build_feedback_message(vf, work_item)
            _log(
                f"    ✗ validation failed ({len(vf.violations)} issue(s)). "
                f"Sending feedback to model."
            )
            # Append the assistant's response then the user feedback to messages.
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": feedback})
            continue

        # Success path: write checkpoint atomically, then the stamp, then log.
        cp_path = window_checkpoint_path(scenario_id, work_item.work_id, intermediates_dir)
        write_json_atomic(cp_path, modified, indent=2)
        write_window_stamp(
            window_stamp_path(scenario_id, work_item.work_id, intermediates_dir),
            expected_stamp,
        )
        write_json_atomic(
            window_llm_log_path(scenario_id, work_item.work_id, intermediates_dir),
            {
                "scenario_id": scenario_id,
                "work_id": work_item.work_id,
                "rule_index": rule.rule_index,
                "trigger_start_iso": work_item.trigger_start_iso,
                "trigger_end_iso": work_item.trigger_end_iso,
                "model": PASS2_MODEL,
                "system_prompt": system_text,
                "turns": conversation_log,
                "total_turns": turn,
                "total_cost_usd": round(cost_meter.total_usd, 4),
            },
            indent=2,
        )
        _log(f"  ✓ {work_item.work_id}: validated after {turn} turn(s), saved checkpoint")
        return modified

    raise Pass2WindowAgentError(
        f"Scenario {scenario_id} work item {work_item.work_id}: "
        f"agent loop failed to produce valid output after "
        f"{PASS2_AGENT_MAX_TURNS} turns. "
        f"Last response in {window_llm_log_path(scenario_id, work_item.work_id, intermediates_dir)} (not written — saved in conversation_log here):\n"
        f"{conversation_log[-1]['response_text'][:500] if conversation_log else '(no turns ran)'}"
    )


# ============================================================
# Render the per-window prompt body
# ============================================================
def _render_user_prompt(
    user_template: str,
    work_item: WorkItem,
    rule: CompiledRule,
    pass1_records_by_tier: dict[str, list[dict]],
) -> str:
    import yaml

    # Work item summary
    summary_lines = [
        f"work_id: {work_item.work_id}",
        f"rule_index: {rule.rule_index}",
        f"trigger_span: {work_item.trigger_start_iso} → {work_item.trigger_end_iso}",
        f"trigger_tier: {rule.trigger.tier}",
        f"trigger_metric: {rule.trigger.metric}",
        f"trigger_record_count: {len(work_item.trigger_record_indices)}",
        f"effect_tiers: {list(work_item.effect_record_indices.keys())}",
        f"pattern_require_lag_zero: {rule.pattern.require_lag_zero}",
    ]
    work_item_summary = "\n  ".join(summary_lines)

    # Rule YAML (compact)
    rule_yaml = yaml.dump(rule.raw_yaml, default_flow_style=False, sort_keys=False)

    # Trigger records (read-only context)
    trigger_records_block = json.dumps(list(work_item.pass1_trigger_records), indent=2)

    # Effect tiers block — for each effect tier, list target_indices + Pass 1 record snapshot
    effect_tier_blocks: list[str] = []
    for tier, indices in work_item.effect_record_indices.items():
        # Collect ALL effects in the rule that target this tier (multi-effect-on-same-record case G12)
        rule_effects_for_tier = [e for e in rule.effects if e.tier == tier]
        adj_descs: list[str] = []
        for e in rule_effects_for_tier:
            if e.adjustment.mode == "additive":
                adj_descs.append(
                    f"  - metric: {e.metric}\n"
                    f"    mode: additive\n"
                    f"    adjustment_bounds: emitted_value ∈ "
                    f"[pass1_value + {e.adjustment.lo}, pass1_value + {e.adjustment.hi}] "
                    f"{e.adjustment.units}\n"
                    f"    timing: {e.timing.mode} (lag {e.timing.lag_records_lo}..{e.timing.lag_records_hi} records)"
                )
            elif e.adjustment.mode == "multiplicative":
                adj_descs.append(
                    f"  - metric: {e.metric}\n"
                    f"    mode: multiplicative\n"
                    f"    target_bounds: emitted_value ∈ "
                    f"[{e.adjustment.target_lo}, {e.adjustment.target_hi}]\n"
                    f"    timing: {e.timing.mode} (lag {e.timing.lag_records_lo}..{e.timing.lag_records_hi} records)"
                )
            else:
                # mode == "none" — should not appear in non-evidence-only rules at this stage
                adj_descs.append(
                    f"  - metric: {e.metric}\n"
                    f"    mode: none  (do NOT modify this metric)"
                )
        adj_block = "\n".join(adj_descs)

        # Snapshot of Pass 1 records the LLM must modify
        snapshot = list(work_item.pass1_effect_records.get(tier, ()))
        snapshot_json = json.dumps(snapshot, indent=2)

        block = (
            f"tier: {tier}\n"
            f"target_indices: {list(indices)}\n"
            f"effects_to_apply:\n{adj_block}\n"
            f"pass1_records_at_target_indices:\n{snapshot_json}"
        )
        effect_tier_blocks.append(block)
    effect_tiers_block = "\n\n".join(effect_tier_blocks)

    return user_template.format(
        work_item_summary=work_item_summary,
        rule_yaml=rule_yaml,
        trigger_records_block=trigger_records_block,
        effect_tiers_block=effect_tiers_block,
    )


# ============================================================
# One streaming LLM call (no caching here — per-window prompts are unique)
# ============================================================
def _send_one_turn(
    *,
    client: "anthropic.Anthropic",
    system: str,
    messages: list[dict[str, Any]],
) -> tuple[str, Any]:
    """Send one streaming call and return (text, usage)."""
    chunk_count = 0
    with client.messages.stream(
        model=PASS2_MODEL,
        max_tokens=PASS2_WINDOW_MAX_TOKENS,
        temperature=PASS2_TEMPERATURE,
        system=system,
        messages=messages,
    ) as stream:
        for _ in stream.text_stream:
            chunk_count += 1
        final = stream.get_final_message()
    if not final.content or final.content[0].type != "text":
        raise Pass2WindowAgentError(
            f"Unexpected response shape from {PASS2_MODEL}: {final.content!r}"
        )
    return final.content[0].text, getattr(final, "usage", None)


# ============================================================
# Response validation
# ============================================================
class _ValidationFailure(Exception):
    """Internal — wraps a list of violation strings for feedback construction."""

    def __init__(self, violations: list[str]):
        super().__init__("; ".join(violations))
        self.violations = violations


def _parse_and_validate_response(
    *,
    response_text: str,
    work_item: WorkItem,
    rule: CompiledRule,
    pass1_records_by_tier: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Strict validation. Raises _ValidationFailure with per-violation details."""
    text = response_text.strip()
    # Strip accidental markdown fencing
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        if text.endswith("```"):
            text = text[:-3].rstrip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise _ValidationFailure([f"response is not valid JSON: {e}"])

    if not isinstance(data, dict) or "modified_records" not in data:
        raise _ValidationFailure(
            ['top-level JSON must be an object with key "modified_records"']
        )
    modified = data["modified_records"]
    if not isinstance(modified, dict):
        raise _ValidationFailure(['"modified_records" must be an object'])

    violations: list[str] = []
    expected_tiers = set(work_item.effect_record_indices.keys())
    got_tiers = set(modified.keys())
    if got_tiers != expected_tiers:
        violations.append(
            f"modified_records keys {sorted(got_tiers)} != expected {sorted(expected_tiers)}"
        )

    # Build per-tier effect metrics + adjustment lookup
    effects_by_tier_metric: dict[tuple[str, str], EffectSpec] = {
        (e.tier, e.metric): e for e in rule.effects
    }

    output: dict[str, list[dict]] = {tier: [] for tier in expected_tiers}
    for tier, expected_indices in work_item.effect_record_indices.items():
        entries = modified.get(tier, [])
        if not isinstance(entries, list):
            violations.append(f"tier {tier}: must be a list")
            continue

        got_indices = []
        entry_by_index: dict[int, dict] = {}
        for ei, entry in enumerate(entries):
            if not isinstance(entry, dict) or "index" not in entry or "record" not in entry:
                violations.append(f"tier {tier} entry {ei}: must have keys 'index' and 'record'")
                continue
            idx = entry["index"]
            if not isinstance(idx, int):
                violations.append(f"tier {tier} entry {ei}: 'index' must be int, got {type(idx).__name__}")
                continue
            got_indices.append(idx)
            entry_by_index[idx] = entry["record"]

        # Index set must match exactly
        if sorted(got_indices) != list(expected_indices):
            violations.append(
                f"tier {tier}: emitted indices {sorted(got_indices)} != expected {list(expected_indices)}"
            )

        # Per-record validation
        tier_arr = pass1_records_by_tier.get(tier, [])
        rule_metrics_for_tier = {e.metric for e in rule.effects if e.tier == tier}
        for idx in expected_indices:
            if idx not in entry_by_index:
                continue  # already counted as missing-index violation above
            emitted = entry_by_index[idx]
            if not isinstance(emitted, dict):
                violations.append(f"tier {tier} idx {idx}: record must be an object")
                continue
            pass1_rec = tier_arr[idx]

            # 1. Schema: same keys as Pass 1
            missing = set(pass1_rec.keys()) - set(emitted.keys())
            extra = set(emitted.keys()) - set(pass1_rec.keys())
            if missing:
                violations.append(f"tier {tier} idx {idx}: missing fields {sorted(missing)}")
            if extra:
                violations.append(f"tier {tier} idx {idx}: extra fields {sorted(extra)}")

            # 2. Timestamp must equal Pass 1 exactly
            if emitted.get("timestamp") != pass1_rec.get("timestamp"):
                violations.append(
                    f"tier {tier} idx {idx}: timestamp modified "
                    f"({pass1_rec.get('timestamp')!r} → {emitted.get('timestamp')!r})"
                )

            # 3. Modified metrics: within bounds
            for metric in rule_metrics_for_tier:
                effect = effects_by_tier_metric[(tier, metric)]
                p1_val = pass1_rec.get(metric)
                em_val = emitted.get(metric)
                if not isinstance(em_val, (int, float)):
                    violations.append(
                        f"tier {tier} idx {idx} field {metric}: must be numeric, got {em_val!r}"
                    )
                    continue
                if not isinstance(p1_val, (int, float)):
                    continue
                lo, hi = effect.adjustment.applies_to_value(float(p1_val))
                # Round tolerance (LLM emits 1-decimal latencies, may be off by 0.01)
                if not (lo - 0.01 <= float(em_val) <= hi + 0.01):
                    violations.append(
                        f"tier {tier} idx {idx} field {metric}: emitted {em_val} not in "
                        f"allowed bounds [{lo:.3f}, {hi:.3f}] "
                        f"(Pass 1 baseline {p1_val}, adjustment {effect.adjustment.raw_text!r})"
                    )

            # 4. Unmodified fields: must equal Pass 1 exactly
            for k, v in pass1_rec.items():
                if k == "timestamp":
                    continue
                if k in rule_metrics_for_tier:
                    continue
                if emitted.get(k) != v:
                    violations.append(
                        f"tier {tier} idx {idx} field {k}: must equal Pass 1 "
                        f"({v!r}) but got {emitted.get(k)!r} (only "
                        f"{sorted(rule_metrics_for_tier)} may be modified)"
                    )

            output[tier].append(emitted)

    if violations:
        raise _ValidationFailure(violations)

    return output


# ============================================================
# Feedback message construction for the next turn
# ============================================================
def _build_feedback_message(failure: _ValidationFailure, work_item: WorkItem) -> str:
    """Produce a focused user message naming each violation."""
    lines = [
        f"Your previous emission failed validation for work item "
        f"{work_item.work_id}. Specific violations:",
    ]
    for i, v in enumerate(failure.violations[:20], 1):  # cap to avoid runaway prompts
        lines.append(f"  {i}. {v}")
    if len(failure.violations) > 20:
        lines.append(f"  ... and {len(failure.violations) - 20} more.")
    lines.append("")
    lines.append(
        "Re-emit ONLY the records that violated the rules. Use the same "
        "'modified_records' top-level schema. Each record must include ALL "
        "fields (modified metrics within the stated bounds; every other "
        "field bit-equal to Pass 1; timestamp unchanged). Do NOT emit records "
        "that already passed validation in the previous turn."
    )
    return "\n".join(lines)
