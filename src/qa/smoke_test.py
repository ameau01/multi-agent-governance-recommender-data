"""Scenario-quality smoke test — Opus recommendation + Haiku judge.

Two phases:

  Phase 4 (smoke_test): generate_smoke_test_recommendation() calls Opus 4.6
  per scenario and saves SmokeTestRecommendation to
  intermediates/NN/smoke_test.json.

  Phase 5 (smoke_test_judge): judge_smoke_test_recommendation() reads the
  Opus output + the scenario spec, compares on 4 fields, uses Haiku for
  the specific_change LLM-as-judge call.

The split makes the cheap-but-Opus-dependent phase recoverable without
re-spending Opus tokens on resume.

See docs/internal/scenario-quality-smoke-test.md.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from generator.checkpoint import (
    checkpoint_path,
    write_json_atomic,
    write_pydantic_atomic,
)
from generator.constants import (
    INTERMEDIATES_DIR,
    JUDGE_MAX_TOKENS,
    SCENARIOS_OUTPUT_DIR,
    SMOKE_TEST_JUDGE_MODEL,
    SMOKE_TEST_MAX_TOKENS,
    SMOKE_TEST_MODEL,
)
from generator.llm_client import LLMClient
from generator.spec_loader import load_all_specs, load_spec
from generator.types import ScenarioSpec


# ============================================================
# Result types
# ============================================================
class SmokeTestRecommendation(BaseModel):
    """Opus's output for one scenario, before judging.

    Persisted to intermediates/NN/smoke_test.json.
    """

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    finding_type: Literal[
        "issue_found", "no_issue_found", "insufficient_data", "diagnostic_deferral"
    ]
    primary_tier: Literal["compute", "database", "cache", "network"] | None = None
    secondary_tier: Literal["compute", "database", "cache", "network"] | None = None
    action_category: str | None = None
    specific_change: str
    raw_model_response: str | None = None


class FieldComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str | None
    produced: str | None
    match: bool


class SmokeTestJudgeResult(BaseModel):
    """Per-scenario judge outcome.

    Persisted to intermediates/NN/smoke_test_judge.json.
    """

    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    outcome: Literal["pass", "partial", "fail"]
    finding_type: FieldComparison
    primary_tier: FieldComparison
    action_category: FieldComparison
    specific_change: FieldComparison


class SmokeTestReport(BaseModel):
    """Aggregate report across all scenarios.

    Persisted to intermediates/smoke_test_report.json.
    """

    model_config = ConfigDict(extra="forbid")
    ran_at: str
    scenarios_tested: int
    passed: int
    partial: int
    failed: int
    aggregate_status: Literal["green", "yellow", "red"]
    details: list[SmokeTestJudgeResult]


# Max output tokens come from constants.py, which reads from .env
# (DATAGENSMOKE_TEST_MAX_TOKENS / DATAGENJUDGE_MAX_TOKENS).


# ============================================================
# Phase 4: smoke_test — Opus recommendation generation
# ============================================================
def generate_smoke_test_recommendation(
    scenario_id: str,
    scenarios_dir: Path | None = None,
    *,
    intermediates_dir: Path | None = None,
) -> SmokeTestRecommendation:
    """Run Phase 4 for one scenario: call Opus, parse, return.

    Auto-builds the two cheap, deterministic upstream artifacts
    (metadata.json and main.tf) if they're missing from the scenario
    folder — neither costs an LLM call, and the smoke test prompt
    cannot be assembled without them. This keeps the user from having
    to remember to run `build-metadata` and `build-terraform`
    separately before every smoke-test run.
    """
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    scenario_dir = scenarios_dir / scenario_id
    if not scenario_dir.exists():
        raise FileNotFoundError(
            f"Scenario folder not found: {scenario_dir}. "
            f"Run Phases 1-3 for {scenario_id} first."
        )

    # Prestep — build metadata.json + main.tf if missing.
    # No-op when both files already exist.
    _ensure_metadata_and_terraform(scenario_id, scenarios_dir)

    prompt = _build_smoke_test_prompt(scenario_dir)
    client = LLMClient(model=SMOKE_TEST_MODEL, max_tokens=SMOKE_TEST_MAX_TOKENS, temperature=0.2)

    log_path = intermediates_dir / scenario_id / "smoke_test_llm_log.json"
    response = _call_smoke_test_llm(client, prompt, log_path, scenario_id)

    # Parse JSON. Retry once on parse error.
    try:
        data = _parse_smoke_test_response(response, scenario_id)
    except ValueError:
        response = _call_smoke_test_llm(client, prompt + "\n\nReturn ONLY the JSON object — no markdown, no explanation.", log_path, scenario_id)
        data = _parse_smoke_test_response(response, scenario_id)

    rec = SmokeTestRecommendation(
        scenario_id=scenario_id,
        finding_type=data["finding_type"],
        primary_tier=data.get("primary_tier"),
        secondary_tier=data.get("secondary_tier"),
        action_category=data.get("action_category"),
        specific_change=data["specific_change"],
        raw_model_response=response,
    )
    return rec


def write_smoke_test_recommendation(
    rec: SmokeTestRecommendation, intermediates_dir: Path | None = None,
) -> Path:
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    target = checkpoint_path(rec.scenario_id, "smoke_test", intermediates_dir)
    write_pydantic_atomic(target, rec)
    return target


def read_smoke_test_recommendation(
    scenario_id: str, intermediates_dir: Path | None = None,
) -> SmokeTestRecommendation:
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    target = checkpoint_path(scenario_id, "smoke_test", intermediates_dir)
    if not target.exists():
        raise FileNotFoundError(
            f"Smoke test recommendation not found: {target}. "
            f"Run smoke-test for {scenario_id} first."
        )
    return SmokeTestRecommendation.model_validate(json.loads(target.read_text()))


def generate_smoke_test_recommendations_all(
    scenarios_dir: Path | None = None,
    *,
    intermediates_dir: Path | None = None,
) -> dict[str, SmokeTestRecommendation]:
    """Run Phase 4 across all 18 scenarios. Resume via checkpoint.partition_scenarios."""
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    specs = load_all_specs()
    results: dict[str, SmokeTestRecommendation] = {}
    for spec in specs:
        scenario_id = spec.scenario_id
        existing = checkpoint_path(scenario_id, "smoke_test", intermediates_dir)
        if existing.exists():
            try:
                results[scenario_id] = SmokeTestRecommendation.model_validate(
                    json.loads(existing.read_text())
                )
                print(f"  [{scenario_id}] smoke_test — skipped (already complete)")
                continue
            except (ValidationError, json.JSONDecodeError):
                pass  # fall through to regenerate
        print(f"  [{scenario_id}] smoke_test — generating Opus recommendation...")
        rec = generate_smoke_test_recommendation(
            scenario_id, scenarios_dir, intermediates_dir=intermediates_dir,
        )
        write_smoke_test_recommendation(rec, intermediates_dir)
        results[scenario_id] = rec
    return results


# ============================================================
# Phase 5: smoke_test_judge — Haiku judging
# ============================================================
def judge_smoke_test_recommendation(
    scenario_id: str,
    recommendation: SmokeTestRecommendation,
    spec: ScenarioSpec,
) -> SmokeTestJudgeResult:
    """Compare the Opus recommendation against the spec's target on 4 fields."""
    target = spec.target_recommendation

    ft_match = recommendation.finding_type == target.get("finding_type")
    pt_match = (recommendation.primary_tier or None) == (target.get("primary_tier") or None)
    ac_match = (recommendation.action_category or None) == (target.get("action_category") or None)

    target_change = target.get("specific_change", "")
    sc_match = _judge_specific_change(target_change, recommendation.specific_change)

    matches = sum([ft_match, pt_match, ac_match, sc_match])
    if matches == 4:
        outcome = "pass"
    elif matches >= 2:
        outcome = "partial"
    else:
        outcome = "fail"

    return SmokeTestJudgeResult(
        scenario_id=scenario_id,
        outcome=outcome,
        finding_type=FieldComparison(
            target=str(target.get("finding_type")) if target.get("finding_type") else None,
            produced=recommendation.finding_type,
            match=ft_match,
        ),
        primary_tier=FieldComparison(
            target=str(target.get("primary_tier")) if target.get("primary_tier") else None,
            produced=recommendation.primary_tier,
            match=pt_match,
        ),
        action_category=FieldComparison(
            target=str(target.get("action_category")) if target.get("action_category") else None,
            produced=recommendation.action_category,
            match=ac_match,
        ),
        specific_change=FieldComparison(
            target=target_change[:200],
            produced=recommendation.specific_change[:200],
            match=sc_match,
        ),
    )


def write_smoke_test_judge(
    result: SmokeTestJudgeResult, intermediates_dir: Path | None = None,
) -> Path:
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    target = checkpoint_path(result.scenario_id, "smoke_test_judge", intermediates_dir)
    write_pydantic_atomic(target, result)
    return target


def judge_smoke_test_recommendations_all(
    scenarios_dir: Path | None = None,
    *,
    intermediates_dir: Path | None = None,
) -> dict[str, SmokeTestJudgeResult]:
    """Run Phase 5 across all 18 scenarios. Resume-aware."""
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    specs = load_all_specs()
    results: dict[str, SmokeTestJudgeResult] = {}
    for spec in specs:
        scenario_id = spec.scenario_id
        existing = checkpoint_path(scenario_id, "smoke_test_judge", intermediates_dir)
        if existing.exists():
            try:
                results[scenario_id] = SmokeTestJudgeResult.model_validate(
                    json.loads(existing.read_text())
                )
                print(f"  [{scenario_id}] smoke_test_judge — skipped (already complete)")
                continue
            except (ValidationError, json.JSONDecodeError):
                pass
        rec_path = checkpoint_path(scenario_id, "smoke_test", intermediates_dir)
        if not rec_path.exists():
            print(f"  [{scenario_id}] smoke_test_judge — skipped (smoke_test not run)")
            continue
        rec = SmokeTestRecommendation.model_validate(json.loads(rec_path.read_text()))
        print(f"  [{scenario_id}] smoke_test_judge — judging...")
        result = judge_smoke_test_recommendation(scenario_id, rec, spec)
        write_smoke_test_judge(result, intermediates_dir)
        results[scenario_id] = result
    return results


# ============================================================
# Aggregate report
# ============================================================
def build_smoke_test_report(
    judge_results: dict[str, SmokeTestJudgeResult],
) -> SmokeTestReport:
    """Aggregate per-scenario judge results into the aggregate report.

    Threshold per scenario-quality-smoke-test.md §3:
      - ≥14 pass: GREEN
      - 12-13 pass: YELLOW
      - ≤11 pass: RED
    """
    passed = sum(1 for r in judge_results.values() if r.outcome == "pass")
    partial = sum(1 for r in judge_results.values() if r.outcome == "partial")
    failed = sum(1 for r in judge_results.values() if r.outcome == "fail")
    total = passed + partial + failed
    if passed >= 14:
        status: Literal["green", "yellow", "red"] = "green"
    elif passed >= 12:
        status = "yellow"
    else:
        status = "red"
    return SmokeTestReport(
        ran_at=datetime.now(timezone.utc).isoformat(),
        scenarios_tested=total,
        passed=passed,
        partial=partial,
        failed=failed,
        aggregate_status=status,
        details=list(judge_results.values()),
    )


# ============================================================
# Helpers
# ============================================================
def _ensure_metadata_and_terraform(
    scenario_id: str, scenarios_dir: Path,
) -> None:
    """Build scenarios/NN/metadata.json and main.tf if missing.

    Both are produced by deterministic, no-LLM builders
    (generator.metadata + generator.terraform) and are
    prerequisites for the smoke-test prompt. Building them on
    demand here means callers (CLI per-scenario, CLI -all,
    programmatic) never have to remember the prestep.

    No-op when both files already exist on disk — this keeps the
    fast path fast on re-runs and avoids any risk of clobbering
    a hand-edited file the user wants to preserve.
    """
    scenario_dir = scenarios_dir / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = scenario_dir / "metadata.json"
    terraform_path = scenario_dir / "main.tf"
    if metadata_path.exists() and terraform_path.exists():
        return

    # Lazy import — keeps the smoke-test module importable even
    # if someone is unit-testing it without the generator package.
    from generator import metadata as metadata_module
    from generator import terraform as terraform_module

    spec = load_spec(scenario_id)
    meta = metadata_module.build_metadata(spec)

    if not metadata_path.exists():
        metadata_module.write_metadata(meta, scenario_dir)
    if not terraform_path.exists():
        hcl = terraform_module.render_terraform(meta)
        terraform_module.validate_terraform(hcl, meta)
        terraform_module.write_terraform(hcl, scenario_dir)


def _build_smoke_test_prompt(scenario_dir: Path) -> str:
    """Bundle metadata (target_recommendation + evaluation_properties stripped),
    telemetry summaries (NOT raw records), correlation_evidence, and main.tf.
    """
    metadata_full = json.loads((scenario_dir / "metadata.json").read_text())
    # Strip ground truth before showing to model
    metadata_redacted = {k: v for k, v in metadata_full.items()
                         if k not in ("target_recommendation", "evaluation_properties")}

    # Telemetry summaries
    summaries = {}
    for tier in ("compute", "database", "cache", "network"):
        f = scenario_dir / f"{tier}_telemetry.json"
        if not f.exists():
            continue
        records = json.loads(f.read_text())
        if not records:
            continue
        summaries[tier] = _summarize_telemetry(records)

    correlations = json.loads((scenario_dir / "correlation_evidence.json").read_text())
    terraform = (scenario_dir / "main.tf").read_text()

    return f"""You are a senior FinOps / SRE consultant reviewing a single cloud application. You have access to two weeks of telemetry summaries, the scenario metadata, cross-tier correlation evidence, and the Terraform infrastructure definition. Produce a single balanced recommendation that addresses cost, performance, and reliability trade-offs.

Output ONLY a JSON object matching this schema (no markdown, no explanation):
{{
  "finding_type": "issue_found | no_issue_found | insufficient_data | diagnostic_deferral",
  "primary_tier": "compute | database | cache | network | null",
  "secondary_tier": "compute | database | cache | network | null",
  "action_category": "rightsizing | replica_adjustment | pool_sizing | scaling_policy_change | load_balancer_reconfiguration | query_cache_optimization | network_topology_change | sla_review | null",
  "specific_change": "free text — what specifically should change"
}}

## SCENARIO METADATA (target_recommendation and evaluation_properties redacted)

{json.dumps(metadata_redacted, indent=2)}

## TELEMETRY SUMMARIES (14-day window, 15-min intervals)

{json.dumps(summaries, indent=2)}

## CROSS-TIER CORRELATION EVIDENCE

{json.dumps(correlations, indent=2)}

## TERRAFORM INFRASTRUCTURE

```hcl
{terraform}
```

Output the JSON only.
"""


def _summarize_telemetry(records: list[dict]) -> dict:
    """Compact summary of a telemetry array: p50/p95/mean/min/max/stddev per metric."""
    if not records:
        return {}
    summary = {}
    sample = records[0]
    for metric_key in sample.keys():
        if metric_key in ("timestamp", "instance_id"):
            continue
        values = [r[metric_key] for r in records if isinstance(r.get(metric_key), (int, float))]
        if not values:
            continue
        values.sort()
        n = len(values)
        mean = sum(values) / n
        p50 = values[n // 2]
        p95 = values[int(n * 0.95)]
        v_min, v_max = values[0], values[-1]
        variance = sum((v - mean) ** 2 for v in values) / n
        import math
        stddev = math.sqrt(variance)
        summary[metric_key] = {
            "p50": round(p50, 3), "p95": round(p95, 3),
            "mean": round(mean, 3), "min": round(v_min, 3), "max": round(v_max, 3),
            "stddev": round(stddev, 3),
        }
    return summary


def _call_smoke_test_llm(
    client: LLMClient, prompt: str, log_path: Path, scenario_id: str,
) -> str:
    """Call the smoke-test LLM. Uses a single user message (no template caching)."""
    response = client._client.messages.create(
        model=client.model,
        max_tokens=client.max_tokens,
        temperature=client.temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    # Manual log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_payload = {
        "model": client.model,
        "scenario_id": scenario_id,
        "prompt": prompt[:500] + "..." if len(prompt) > 500 else prompt,
        "response": text,
        "usage": {
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
        },
    }
    write_json_atomic(log_path, log_payload)
    return text


def _parse_smoke_test_response(response: str, scenario_id: str) -> dict:
    """Strip markdown if present, parse JSON, validate required fields."""
    text = response.strip()
    if text.startswith("```"):
        import re
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Scenario {scenario_id}: smoke test response not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"Scenario {scenario_id}: expected JSON object, got {type(data).__name__}")
    if "finding_type" not in data:
        raise ValueError(f"Scenario {scenario_id}: missing finding_type field")
    if "specific_change" not in data:
        raise ValueError(f"Scenario {scenario_id}: missing specific_change field")
    # Normalize null-strings to None
    for k in ("primary_tier", "secondary_tier", "action_category"):
        if data.get(k) in ("null", "None", ""):
            data[k] = None
    return data


def _judge_specific_change(target: str, produced: str) -> bool:
    """Haiku LLM-as-judge: one-line YES/NO comparison.

    Falls back to substring match if Haiku call fails.
    """
    if not target or not produced:
        return False
    try:
        client = LLMClient(
            model=SMOKE_TEST_JUDGE_MODEL,
            max_tokens=JUDGE_MAX_TOKENS,
            temperature=0.0,
        )
        # Direct prompt (no template) — judge call is too small to warrant caching
        response = client._client.messages.create(
            model=client.model,
            max_tokens=client.max_tokens,
            temperature=client.temperature,
            messages=[{
                "role": "user",
                "content": (
                    "Do these two recommendations propose substantively the same "
                    "change to the same resources? Answer YES or NO only.\n"
                    f"A: {target}\nB: {produced}"
                ),
            }],
        )
        verdict = response.content[0].text.strip().upper()
        return verdict.startswith("YES")
    except Exception as e:
        print(f"    Judge LLM call failed ({type(e).__name__}); falling back to substring check")
        # Crude fallback: do they share at least one significant word?
        target_words = set(w.lower() for w in target.split() if len(w) > 4)
        produced_words = set(w.lower() for w in produced.split() if len(w) > 4)
        overlap = target_words & produced_words
        return len(overlap) >= 2
