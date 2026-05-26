"""Pass 2 generator — orchestrator over planner, verification, agent loop, merger.

Phase 2A (planner)  — pass2_planner.plan_pass2
Phase 2B (verification + agent loop) — this module + pass2_agent.run_window_agent_loop
Phase 2C (merge + correlation_evidence) — pass2_merger.merge / compute_correlation_evidence

This module's job is the orchestration:

  1. Build a Pass 2 plan from the spec + Pass 1.
  2. Persist the plan to intermediates/NN/pass2_plan.json for inspection.
  3. Run the mandatory verification LLM call (G10), persist its result.
  4. Resume-aware partitioning: for each work item, check whether a
     stamp-matching checkpoint already exists; if so, reuse it. Otherwise
     dispatch to the agent loop.
  5. Merge all window outputs into a Pass 2 baseline (Phase 2C).
  6. Compute correlation_evidence (Pearson + alignment + lag-zero check).
  7. Persist Pass 2 output atomically.

All writes are atomic (tmp file + fsync + rename). All log lines are
timestamped via _log(). The agent loop's per-window cost is tracked in a
shared CostMeter so a runaway loop can't blow past the per-scenario
budget — Pass2CostCeilingExceeded aborts cleanly with checkpoints intact
for a subsequent resume.

For scenarios with empty pass2_correlations:
  - Phase 2A produces an empty work plan.
  - Phase 2B verification call still runs (G10).
  - Phase 2C merger copies Pass 1 verbatim and emits an empty
    correlation_evidence list.
  - Final Pass 2 output is byte-equal to Pass 1 (except `pass_=2`).

The previous skip-the-LLM-entirely code path is gone (G55).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from contracts import CorrelationPair
from generator.checkpoint import (
    checkpoint_path,
    partition_windows,
    sha256_bytes_hex,
    sha256_file_hex,
    window_checkpoint_path,
    window_checkpoint_valid,
    write_json_atomic,
    write_pydantic_atomic,
    WindowStamp,
)
from generator.constants import (
    INTERMEDIATES_DIR,
    PASS2_MODEL,
    PASS2_SCENARIO_MAX_COST_USD,
    PASS2_TEMPERATURE,
    PASS2_VERIFICATION_ENABLED,
    PASS2_VERIFICATION_MAX_TOKENS,
    PASS2_VERIFICATION_SAMPLE_PER_TIER,
)
from generator.pass2_agent import (
    CostMeter,
    PASS2_PROMPT_PATH,
    _make_client,
    _split_prompt,
    run_window_agent_loop,
)
from generator.pass2_merger import compute_correlation_evidence, merge
from generator.pass2_planner import plan_pass2, write_plan
from generator.pass2_types import (
    Pass2CostCeilingExceeded,
    Pass2Plan,
    Pass2PlanInfeasible,
    Pass2WindowAgentError,
    VerificationResult,
)
from generator.types import Pass1Output, Pass2Output, ScenarioSpec


_VERIFICATION_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "pass2_verification.txt"

_TIER_KEYS = {
    "compute": "Compute_Metrics",
    "database": "Database_Metrics",
    "cache": "Cache_Metrics",
    "network": "Network_Metrics",
}


def _log(msg: str = "") -> None:
    if not msg.strip():
        print(msg, flush=True)
        return
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================
# Public entrypoint
# ============================================================
def generate_pass2(
    spec: ScenarioSpec,
    pass1_output: Pass1Output,
    *,
    intermediates_dir: Path | None = None,
) -> tuple[Pass2Output, list[CorrelationPair]]:
    """Run Pass 2 (planner + verification + agent loop + merge) for one scenario.

    Resumable: per-window checkpoints are reused if their provenance stamp
    matches the current Pass 1 hash + rule index + prompt hash + trigger span.

    Returns:
        (Pass2Output, list[CorrelationPair])

    Raises:
        Pass2PlanInfeasible: if Pass 1 cannot satisfy a rule's pattern.
        Pass2WindowAgentError: if an agent loop exhausts MAX_TURNS on a window.
        Pass2CostCeilingExceeded: if per-scenario cost ceiling is hit.
    """
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    scenario_dir = intermediates_dir / spec.scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)

    _log(f"  Pass 2 [{spec.scenario_id}]: starting")
    _log(f"  Pass 2 [{spec.scenario_id}]: Phase 2A — building plan from Pass 1")
    plan = plan_pass2(spec, pass1_output)

    # Persist the plan for inspection / debugging.
    plan_path = scenario_dir / "pass2_plan.json"
    write_plan(plan, plan_path)
    _log(
        f"  Pass 2 [{spec.scenario_id}]: plan written → {plan_path.name} "
        f"({len(plan.rules)} rule(s), {len(plan.work_items)} work item(s))"
    )
    for rule in plan.rules:
        pv = plan.pattern_verification[rule.rule_index]
        flags: list[str] = []
        if rule.pattern.evidence_only:
            flags.append("evidence_only")
        if rule.pattern.require_lag_zero:
            flags.append("lag_zero")
        flag_str = f"  [{','.join(flags)}]" if flags else ""
        _log(
            f"    rule {rule.rule_index}: {rule.trigger.tier}.{rule.trigger.metric} "
            f"{rule.trigger.condition_op} {rule.trigger.condition_value} → "
            f"{len(rule.effects)} effect(s){flag_str}  "
            f"(feasibility: {pv.qualifying_days}/{pv.required_days} days ✓)"
        )

    # Phase 2B — verification call (G10: mandatory per-scenario LLM coverage)
    if PASS2_VERIFICATION_ENABLED:
        _log(f"  Pass 2 [{spec.scenario_id}]: Phase 2B(0) — verification call (mandatory per-scenario)")
        verification = _run_verification_call(
            spec=spec, pass1=pass1_output, intermediates_dir=intermediates_dir,
        )
        _log(
            f"  Pass 2 [{spec.scenario_id}]: verification verdict={verification.verdict} "
            f"({len(verification.concerns)} concern(s))"
        )
        for c in verification.concerns:
            _log(f"      concern: {c}")

    # Phase 2B — per-window agent loop
    pass1_records_by_tier: dict[str, list[dict]] = {
        tier: [dict(r) if hasattr(r, "keys") else r.model_dump(mode="json")
               for r in getattr(pass1_output, key)]
        for tier, key in _TIER_KEYS.items()
    }

    prompt_sha = sha256_file_hex(PASS2_PROMPT_PATH)
    pass1_sha = plan.pass1_sha256

    # Resume: which windows already have valid stamped checkpoints?
    expected_stamps = {
        w.work_id: WindowStamp(
            pass1_sha256=pass1_sha,
            rule_index=w.rule_index,
            prompt_sha256=prompt_sha,
            trigger_start_iso=w.trigger_start_iso,
            trigger_end_iso=w.trigger_end_iso,
        )
        for w in plan.work_items
    }
    partition = partition_windows(
        scenario_id=spec.scenario_id,
        work_ids=[w.work_id for w in plan.work_items],
        expected_stamps=expected_stamps,
        intermediates_dir=intermediates_dir,
    )
    _log(
        f"  Pass 2 [{spec.scenario_id}]: Phase 2B(1) — agent loop  "
        f"(resume: {len(partition.completed)} window(s) cached, "
        f"{len(partition.remaining)} window(s) to run)"
    )

    cost_meter = CostMeter(ceiling_usd=PASS2_SCENARIO_MAX_COST_USD)
    rules_by_index = {r.rule_index: r for r in plan.rules}
    window_outputs: dict[str, dict[str, list[dict]]] = {}

    for work_item in plan.work_items:
        if work_item.work_id in partition.completed:
            cp = window_checkpoint_path(spec.scenario_id, work_item.work_id, intermediates_dir)
            window_outputs[work_item.work_id] = json.loads(cp.read_text())
            continue
        rule = rules_by_index[work_item.rule_index]
        try:
            window_outputs[work_item.work_id] = run_window_agent_loop(
                scenario_id=spec.scenario_id,
                work_item=work_item,
                rule=rule,
                pass1_records_by_tier=pass1_records_by_tier,
                pass1_sha256=pass1_sha,
                prompt_sha256=prompt_sha,
                intermediates_dir=intermediates_dir,
                cost_meter=cost_meter,
            )
        except (Pass2WindowAgentError, Pass2CostCeilingExceeded) as e:
            _log(f"  Pass 2 [{spec.scenario_id}]: ✗ {type(e).__name__}: {e}")
            raise

    _log(
        f"  Pass 2 [{spec.scenario_id}]: Phase 2B done. "
        f"Total cost so far: ${cost_meter.total_usd:.4f}"
    )

    # Phase 2C — merge + correlation_evidence
    _log(f"  Pass 2 [{spec.scenario_id}]: Phase 2C — merging modifications")
    pass2 = merge(pass1_output, plan, window_outputs)
    _log(f"  Pass 2 [{spec.scenario_id}]: computing correlation_evidence")
    pairs = compute_correlation_evidence(plan, pass2)
    _log(
        f"  Pass 2 [{spec.scenario_id}]: ✓ complete — "
        f"{sum(len(getattr(pass2, k)) for k in _TIER_KEYS.values())} total records, "
        f"{len(pairs)} correlation_evidence pair(s)"
    )
    return pass2, pairs


# ============================================================
# Phase 2B(0) — Verification call (G10)
# ============================================================
def _run_verification_call(
    *,
    spec: ScenarioSpec,
    pass1: Pass1Output,
    intermediates_dir: Path,
) -> VerificationResult:
    """Always-runs LLM call that samples Pass 1 records and asks for a verdict.

    Output is persisted to intermediates/NN/pass2_verification.json. Resume
    short-circuits if the same Pass 1 hash already has a verification.
    """
    out_path = intermediates_dir / spec.scenario_id / "pass2_verification.json"
    pass1_bytes = pass1.model_dump_json().encode()
    pass1_sha = sha256_bytes_hex(pass1_bytes)

    # Resume short-circuit
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
            if existing.get("pass1_sha256") == pass1_sha:
                _log(f"      ↻ verification: existing artifact matches Pass 1 hash, reusing")
                return VerificationResult(
                    scenario_id=spec.scenario_id,
                    sample_indices={
                        k: tuple(v) for k, v in existing.get("sample_indices", {}).items()
                    },
                    verdict=existing.get("verdict", "pass"),
                    concerns=tuple(existing.get("concerns", [])),
                    raw_response=existing.get("raw_response", ""),
                )
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            pass

    # Sample records evenly across the 14-day window for each active tier
    sample_indices: dict[str, tuple[int, ...]] = {}
    sample_block_parts: list[str] = []
    for tier, key in _TIER_KEYS.items():
        arr = getattr(pass1, key)
        if not arr:
            continue
        n = len(arr)
        if n <= PASS2_VERIFICATION_SAMPLE_PER_TIER:
            indices = tuple(range(n))
        else:
            step = max(1, n // PASS2_VERIFICATION_SAMPLE_PER_TIER)
            indices = tuple(range(0, n, step))[:PASS2_VERIFICATION_SAMPLE_PER_TIER]
        sample_indices[tier] = indices
        sample_records = [
            arr[i] if isinstance(arr[i], dict) else arr[i].model_dump(mode="json")
            for i in indices
        ]
        sample_block_parts.append(
            f"--- {tier} (sampled {len(indices)} of {n} records) ---\n"
            + json.dumps(sample_records, indent=2)
        )
    sample_records_block = "\n\n".join(sample_block_parts) if sample_block_parts else "(no active tiers)"

    # Render verification prompt
    import yaml
    template = _VERIFICATION_PROMPT_PATH.read_text(encoding="utf-8")
    system_text, user_template = _split_prompt(template)
    bc = spec.business_context or {}
    narrative = spec.narrative or {}
    user_text = user_template.format(
        scenario_id=spec.scenario_id,
        scenario_name=spec.scenario_name,
        scenario_type=spec.scenario_type,
        business_context_description=bc.get("description", ""),
        criticality=bc.get("criticality", "tier-2"),
        scenario_behavioral_notes=(narrative.get("what_this_demonstrates") or "(none)").strip(),
        pass1_metrics_block=yaml.dump(
            spec.pass1_metrics, default_flow_style=False, sort_keys=False,
        ),
        sample_records_block=sample_records_block,
    )

    # Single-turn call
    client = _make_client()
    _log(
        f"      verification: calling {PASS2_MODEL} "
        f"(max_tokens={PASS2_VERIFICATION_MAX_TOKENS}, "
        f"sample_size_per_tier={PASS2_VERIFICATION_SAMPLE_PER_TIER})"
    )
    with client.messages.stream(
        model=PASS2_MODEL,
        max_tokens=PASS2_VERIFICATION_MAX_TOKENS,
        temperature=PASS2_TEMPERATURE,
        system=system_text,
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        for _ in stream.text_stream:
            pass
        final = stream.get_final_message()
    raw_response = final.content[0].text if final.content else ""

    # Parse verdict
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        if text.endswith("```"):
            text = text[:-3].rstrip()
    verdict = "concern"
    concerns: list[str] = []
    try:
        parsed = json.loads(text)
        verdict = parsed.get("verdict", "concern")
        concerns = list(parsed.get("concerns", []) or [])
    except json.JSONDecodeError:
        concerns = [f"verification response was not valid JSON: {raw_response[:200]}"]

    result = VerificationResult(
        scenario_id=spec.scenario_id,
        sample_indices=sample_indices,
        verdict=verdict,  # type: ignore[arg-type]
        concerns=tuple(concerns),
        raw_response=raw_response,
    )
    write_json_atomic(out_path, {
        "scenario_id": spec.scenario_id,
        "pass1_sha256": pass1_sha,
        "sample_indices": {k: list(v) for k, v in sample_indices.items()},
        "verdict": verdict,
        "concerns": concerns,
        "raw_response": raw_response,
    }, indent=2)
    return result


# ============================================================
# Atomic persistence of Pass 2 output
# ============================================================
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
    return Pass2Output.model_validate(json.loads(target.read_text()))
