"""Pipeline orchestrator — runs all stages for one scenario.

build_scenario() executes the five stages in order:

    Pass 1 → Pass 2 → Splitter → Metadata → Terraform → QA

Each stage's output is checkpointed atomically. If any stage fails, the
remaining stages are skipped; the partial output stays on disk for debugging
but the scenario is NOT marked as committed.

This module also exposes per-stage functions (run_pass1_for_scenario,
run_pass2_for_scenario, run_validate_for_scenario) used by the CLI's
per-scenario commands.
"""

from __future__ import annotations
import traceback
from pathlib import Path

from generator import metadata as metadata_module
from generator import pass1 as pass1_module
from generator import pass2 as pass2_module
from generator import splitter as splitter_module
from generator import terraform as terraform_module
from generator.constants import INTERMEDIATES_DIR, SCENARIOS_OUTPUT_DIR
from generator.spec_loader import load_spec
from generator.types import ScenarioBuildResult
from qa import qa_validator


# ============================================================
# Per-stage runners (called by CLI for per-scenario commands)
# ============================================================
def run_pass1_for_scenario(
    scenario_id: str,
    *,
    intermediates_dir: Path | None = None,
) -> Path:
    """Run Pass 1 for one scenario, checkpoint, return the checkpoint path."""
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    spec = load_spec(scenario_id)
    output = pass1_module.generate_pass1(spec, intermediates_dir=intermediates_dir)
    return pass1_module.write_pass1_intermediate(output, intermediates_dir)


def run_pass2_for_scenario(
    scenario_id: str,
    *,
    scenarios_dir: Path | None = None,
    intermediates_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Run Pass 2 + write correlation_evidence. Returns (pass2 path, ce path)."""
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    spec = load_spec(scenario_id)
    pass1_output = pass1_module.read_pass1_intermediate(scenario_id, intermediates_dir)
    pass2_output, pairs = pass2_module.generate_pass2(
        spec, pass1_output, intermediates_dir=intermediates_dir,
    )
    pass2_path = pass2_module.write_pass2_intermediate(pass2_output, intermediates_dir)
    ce_path = splitter_module.write_correlation_evidence(pairs, scenarios_dir / scenario_id)
    # Also split telemetry into the four consumer files
    splitter_module.split_telemetry(pass2_output, scenarios_dir / scenario_id)
    return pass2_path, ce_path


def run_metadata_for_scenario(
    scenario_id: str,
    *,
    scenarios_dir: Path | None = None,
) -> Path:
    """Build + write metadata.json for one scenario."""
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    spec = load_spec(scenario_id)
    meta = metadata_module.build_metadata(spec)
    return metadata_module.write_metadata(meta, scenarios_dir / scenario_id)


def run_terraform_for_scenario(
    scenario_id: str,
    *,
    scenarios_dir: Path | None = None,
) -> Path:
    """Build metadata, render + validate + write main.tf for one scenario."""
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    spec = load_spec(scenario_id)
    meta = metadata_module.build_metadata(spec)
    hcl = terraform_module.render_terraform(meta)
    terraform_module.validate_terraform(hcl, meta)
    return terraform_module.write_terraform(hcl, scenarios_dir / scenario_id)


# ============================================================
# Shared scenario-prerequisites helper
# ============================================================
def ensure_scenario_prerequisites(
    scenario_id: str,
    *,
    scenarios_dir: Path | None = None,
) -> None:
    """Build scenarios/NN/metadata.json and main.tf if missing.

    Both are produced by deterministic, no-LLM builders
    (generator.metadata + generator.terraform). They are required
    inputs for `validate` and `smoke-test`, but neither pass1 nor
    pass2 produces them.

    Idempotent and free: skips entirely when both files already
    exist; never overwrites an existing file. Lets the user run
    any subset of `[pass1, pass2, validate, smoke-test, smoke-test-judge]`
    in order without remembering to manually run `build-metadata`
    and `build-terraform` between pass2 and validate.

    This is the single source of truth for the auto-prestep —
    both `run_validate_for_scenario` and `qa.smoke_test` delegate
    to this function so the two paths can't drift.
    """
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    scenario_dir = scenarios_dir / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = scenario_dir / "metadata.json"
    terraform_path = scenario_dir / "main.tf"
    if metadata_path.exists() and terraform_path.exists():
        return

    spec = load_spec(scenario_id)
    meta = metadata_module.build_metadata(spec)

    if not metadata_path.exists():
        metadata_module.write_metadata(meta, scenario_dir)
    if not terraform_path.exists():
        hcl = terraform_module.render_terraform(meta)
        terraform_module.validate_terraform(hcl, meta)
        terraform_module.write_terraform(hcl, scenario_dir)


def run_validate_for_scenario(
    scenario_id: str,
    *,
    scenarios_dir: Path | None = None,
    intermediates_dir: Path | None = None,
):
    """Run QA validator for one scenario.

    Auto-builds the two deterministic upstream artifacts (metadata.json
    and main.tf) before validating, so that the contract-layer check
    "all expected files exist" doesn't fail after just pass1+pass2.
    """
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR

    # Prestep — same helper smoke_test uses. Idempotent.
    ensure_scenario_prerequisites(scenario_id, scenarios_dir=scenarios_dir)

    spec = load_spec(scenario_id)
    return qa_validator.validate_scenario(
        scenario_id, scenarios_dir, spec, intermediates_dir,
    )


# ============================================================
# Full pipeline for one scenario
# ============================================================
def build_scenario(
    scenario_id: str,
    scenarios_dir: Path | None = None,
    intermediates_dir: Path | None = None,
) -> ScenarioBuildResult:
    """Run Pass 1 → Pass 2 → Splitter → Metadata → Terraform → QA for one scenario.

    Each stage's output is checkpointed. On any failure, partial output stays
    on disk (for debugging) but the scenario is reported as unsuccessful.

    Returns:
        ScenarioBuildResult summarizing what stages completed.
    """
    scenarios_dir = scenarios_dir or SCENARIOS_OUTPUT_DIR
    intermediates_dir = intermediates_dir or INTERMEDIATES_DIR
    stages_completed: list[str] = []
    output_dir = scenarios_dir / scenario_id

    try:
        # Stage 1: Pass 1
        run_pass1_for_scenario(scenario_id, intermediates_dir=intermediates_dir)
        stages_completed.append("pass1")

        # Stage 2: Pass 2 (also writes split telemetry files + correlation_evidence)
        run_pass2_for_scenario(
            scenario_id,
            scenarios_dir=scenarios_dir,
            intermediates_dir=intermediates_dir,
        )
        stages_completed.extend(["pass2", "splitter"])

        # Stage 3: Metadata
        run_metadata_for_scenario(scenario_id, scenarios_dir=scenarios_dir)
        stages_completed.append("metadata")

        # Stage 4: Terraform
        run_terraform_for_scenario(scenario_id, scenarios_dir=scenarios_dir)
        stages_completed.append("terraform")

        # Stage 5: QA
        qa_report = run_validate_for_scenario(
            scenario_id,
            scenarios_dir=scenarios_dir,
            intermediates_dir=intermediates_dir,
        )
        stages_completed.append("qa")
        qa_passed = qa_report.overall == "pass"

        return ScenarioBuildResult(
            scenario_id=scenario_id,
            success=True,
            stages_completed=stages_completed,
            qa_passed=qa_passed,
            error=None,
            output_dir=str(output_dir),
        )
    except Exception as e:
        return ScenarioBuildResult(
            scenario_id=scenario_id,
            success=False,
            stages_completed=stages_completed,
            qa_passed=False,
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            output_dir=str(output_dir),
        )


def build_all_scenarios(
    scenarios_dir: Path | None = None,
    intermediates_dir: Path | None = None,
) -> list[ScenarioBuildResult]:
    """Run build_scenario for all 18 scenarios sequentially."""
    from generator.constants import ALL_SCENARIO_IDS
    results: list[ScenarioBuildResult] = []
    for sid in ALL_SCENARIO_IDS:
        print(f"\n=== Building scenario {sid} ===")
        result = build_scenario(sid, scenarios_dir, intermediates_dir)
        results.append(result)
        if result.success:
            print(f"  ✓ {sid} complete ({'QA pass' if result.qa_passed else 'QA fail'})")
        else:
            print(f"  ✗ {sid} failed at stage {len(result.stages_completed)}: {result.error}")
    return results
