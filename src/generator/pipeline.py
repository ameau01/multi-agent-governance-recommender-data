"""Pipeline orchestrator — runs all stages for one or all scenarios.

The orchestrator coordinates the five stages (Pass 1, Pass 2, splitter, metadata,
Terraform) plus QA validation. A scenario folder is only committed to
`scenarios/NN/` when QA passes both layers.

Flow:

    spec_loader.load_spec(NN)
        │
        ▼
    pass1.generate_pass1(spec)                  → intermediates/NN/pass1.json
        │
        ▼
    pass2.generate_pass2(spec, pass1)           → intermediates/NN/pass2.json
                                                 + correlation_pairs (list)
        │
        ▼
    splitter.split_telemetry(pass2, scenarios/NN/)
    splitter.write_correlation_evidence(pairs, scenarios/NN/)
        │
        ▼
    metadata.build_metadata(spec)
    metadata.write_metadata(meta, scenarios/NN/)
        │
        ▼
    terraform.render_terraform(meta)
    terraform.validate_terraform(hcl, meta)
    terraform.write_terraform(hcl, scenarios/NN/)
        │
        ▼
    qa.qa_validator.validate_scenario(scenarios/NN/, spec, intermediates/NN/)
        │
        ▼
    if QA passes → keep scenarios/NN/, return ScenarioBuildResult(success=True)
    else        → rollback (remove partial output), return result with error
"""

from __future__ import annotations
from pathlib import Path

from generator.types import ScenarioBuildResult


def build_scenario(
    scenario_id: str,
    scenarios_dir: Path,
    intermediates_dir: Path,
    *,
    skip_pass1: bool = False,                # re-use intermediates/NN/pass1.json
    skip_pass2: bool = False,                # re-use intermediates/NN/pass2.json
    skip_qa: bool = False,                   # for debugging only
) -> ScenarioBuildResult:
    """Run the full pipeline for one scenario.

    Args:
        scenario_id: Zero-padded string, e.g. "07".
        scenarios_dir: Where to write the final scenarios/NN/ folder.
        intermediates_dir: Where to write debug-only pass1/pass2 intermediates.
        skip_pass1: If True, re-use intermediates/NN/pass1.json from a prior run.
        skip_pass2: If True, re-use intermediates/NN/pass2.json from a prior run.
        skip_qa: If True, skip QA validation (debug only — never use in production runs).

    Returns:
        ScenarioBuildResult with success flag, stages_completed list, QA verdict,
        and the output_dir path.
    """
    raise NotImplementedError("Phase B.6 — see BUILD_PLAN.md §B.6")


def build_all_scenarios(
    scenarios_dir: Path,
    intermediates_dir: Path,
) -> list[ScenarioBuildResult]:
    """Run the pipeline for all 18 scenarios sequentially.

    Returns:
        List of 18 ScenarioBuildResult, one per scenario.
    """
    raise NotImplementedError("Phase C.1 — see BUILD_PLAN.md §C.1")
