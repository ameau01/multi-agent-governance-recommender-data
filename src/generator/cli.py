"""CLI entry point for the data-gen pipeline.

# Per-scenario commands (individual control)

    python -m generator.cli build NN                Build one scenario end-to-end.
    python -m generator.cli build-metadata NN       Phase A: metadata only, no telemetry.
    python -m generator.cli build-terraform NN      Phase A: main.tf only.
    python -m generator.cli pass1 NN                Phase B: regenerate Pass 1 only.
    python -m generator.cli pass2 NN                Phase B: regenerate Pass 2 only.
    python -m generator.cli validate NN             Run QA validator without regenerating.
    python -m generator.cli smoke-test NN           Run smoke-test recommendation (Opus) for one scenario.
    python -m generator.cli smoke-test-judge NN     Run judge (Haiku) on saved recommendation for one scenario.

# Phase-level commands (manual oversight across all scenarios — RESUMABLE)

These print cost + time estimates, ask for confirmation, then run the phase
across the relevant scenarios. Use these for the supervised pipeline run.

Resume-aware: each command scans `intermediates/` for existing checkpoints
and skips scenarios that already completed successfully. The cost preview
only includes the *remaining* scenarios — interrupted runs cost nothing
extra to resume.

    python -m generator.cli pass1-all              Pass 1 for all 18 scenarios.
    python -m generator.cli pass2-all              Pass 2 for the ~6 correlation scenarios.
    python -m generator.cli validate-all           QA validator across all 18.
    python -m generator.cli smoke-test-all         Smoke-test recommendation (Opus) on all 18.
    python -m generator.cli smoke-test-judge-all   Judge (Haiku) on all saved recommendations.
    python -m generator.cli build-all              Full pipeline on all 18 (no per-phase pauses).

# Flags

    --yes          Skip the "Proceed? [y/N]" confirmation prompt (for scripts/CI).
    --batch        Submit via Anthropic Batches API (50% pricing, ~5-30 min wall time).
                   Sets DATAGEN_BATCH_MODE=true for this invocation.
    --force        Ignore existing checkpoints; re-run every scenario from scratch.
                   Use after a contract bump or major prompt change.

Environment is loaded from .env at the repo root. See `.env.example` for the
required variables (ANTHROPIC_API_KEY + optional LangSmith config).
"""

from __future__ import annotations
import argparse
import os
import sys

from dotenv import load_dotenv

# Load .env before any module that reads env vars. Idempotent — llm_client.py
# also calls load_dotenv() defensively in case it's imported outside the CLI.
load_dotenv()


# ============================================================
# Phase metadata — cost/time estimates, model, checkpoint validation class.
#
# Used by:
#   - _print_phase_preview: show user what's about to happen.
#   - resume logic: skip scenarios that already have a valid checkpoint.
#
# Total scenarios is the maximum the phase applies to; the per-call estimate
# is (cost_estimate_usd / scenarios) so the preview can compute remaining cost
# after subtracting completed scenarios.
# ============================================================
PHASE_ESTIMATES = {
    "pass1": {
        "scenarios": 18,
        "model": "claude-sonnet-4-6",
        "cost_estimate_usd": 101.0,
        "cost_estimate_batch_usd": 50.5,
        "wall_time_estimate_min_interactive": 15,
        "wall_time_estimate_min_batch": 30,
        "checkpoint_filename": "pass1.json",
        "produces_checkpoint": "pass1.json",
    },
    "pass2": {
        "scenarios": 6,                              # only correlation scenarios
        "model": "claude-sonnet-4-6",
        "cost_estimate_usd": 54.0,
        "cost_estimate_batch_usd": 27.0,
        "wall_time_estimate_min_interactive": 8,
        "wall_time_estimate_min_batch": 20,
        "checkpoint_filename": "pass2.json",
        "produces_checkpoint": "pass2.json",
    },
    "validate": {
        "scenarios": 18,
        "model": "(none — deterministic checks, no LLM)",
        "cost_estimate_usd": 0.0,
        "cost_estimate_batch_usd": 0.0,
        "wall_time_estimate_min_interactive": 1,
        "wall_time_estimate_min_batch": 1,
        "checkpoint_filename": "qa_report.json",
        "produces_checkpoint": "qa_report.json",
    },
    "smoke-test": {
        "scenarios": 18,
        "model": "claude-opus-4-6",
        "cost_estimate_usd": 1.44,
        "cost_estimate_batch_usd": 0.72,
        "wall_time_estimate_min_interactive": 5,
        "wall_time_estimate_min_batch": 12,
        "checkpoint_filename": "smoke_test.json",
        "produces_checkpoint": "smoke_test.json",
    },
    "smoke-test-judge": {
        "scenarios": 18,
        "model": "claude-haiku-4-5-20251001",
        "cost_estimate_usd": 0.01,
        "cost_estimate_batch_usd": 0.005,
        "wall_time_estimate_min_interactive": 1,
        "wall_time_estimate_min_batch": 3,
        "checkpoint_filename": "smoke_test_judge.json",
        "produces_checkpoint": "smoke_test_judge.json",
        "requires_phase": "smoke-test",            # must run after smoke-test
    },
}


def _print_phase_preview(
    phase: str,
    batch: bool,
    completed_count: int = 0,
    remaining_count: int | None = None,
    force: bool = False,
) -> None:
    """Print what's about to happen, including resume reflection.

    Args:
        phase: Phase name from PHASE_ESTIMATES keys.
        batch: Whether Batch API mode is enabled.
        completed_count: Number of scenarios with valid existing checkpoints.
        remaining_count: Number that will actually run. Defaults to
            (total - completed_count). Pass explicitly if --force is in effect
            (then remaining = total even though completed > 0).
        force: If True, the preview shows "all N scenarios (--force overrides
            existing checkpoints)".
    """
    est = PHASE_ESTIMATES[phase]
    total = est["scenarios"]
    if remaining_count is None:
        remaining_count = total - completed_count

    mode = "BATCH (50% pricing, async)" if batch else "INTERACTIVE (full pricing, sync)"
    full_cost = est["cost_estimate_batch_usd"] if batch else est["cost_estimate_usd"]
    wall_time = (
        est["wall_time_estimate_min_batch"]
        if batch
        else est["wall_time_estimate_min_interactive"]
    )

    # Pro-rate cost and time to the remaining scenarios (linear approximation).
    if total > 0 and not force:
        pro_rated_cost = full_cost * (remaining_count / total)
        pro_rated_time = max(1, round(wall_time * (remaining_count / total)))
    else:
        pro_rated_cost = full_cost
        pro_rated_time = wall_time

    print(f"=== Phase: {phase} ===")
    print(f"  Model:                {est['model']}")
    print(f"  Mode:                 {mode}")
    if force:
        print(f"  Scenarios to run:     {total} (--force overrides existing checkpoints)")
    elif completed_count > 0:
        print(f"  Scenarios total:      {total}")
        print(f"  Already complete:     {completed_count} (skipped — found valid checkpoint)")
        print(f"  Remaining to run:     {remaining_count}")
        if remaining_count == 0:
            print(f"  → Nothing to do. All {total} scenarios already have valid checkpoints.")
            print(f"    Use --force to re-run all from scratch.")
    else:
        print(f"  Scenarios to run:     {total}")
    print(f"  Estimated cost:       ~${pro_rated_cost:.2f}")
    print(f"  Estimated time:       ~{pro_rated_time} minutes")
    if "requires_phase" in est:
        print(f"  Required prior phase: {est['requires_phase']} (must have run first)")
    print()


def _confirm(message: str = "Proceed?") -> bool:
    """Ask for yes/no confirmation. Returns True on 'y' or 'yes' (case-insensitive)."""
    try:
        response = input(f"{message} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return response in ("y", "yes")


def _run_phase(phase: str, args: argparse.Namespace) -> int:
    """Top-level handler for phase-level commands (pass1-all, pass2-all, etc.).

    Resume-aware: scans intermediates/ for valid checkpoints, skips completed
    scenarios, shows pro-rated cost preview, runs only remaining scenarios.
    Each scenario's output is written atomically as it completes.
    """
    batch = getattr(args, "batch", False)
    force = getattr(args, "force", False)
    yes = getattr(args, "yes", False)

    # Imports here to avoid loading the full pipeline at CLI parse time
    from generator.checkpoint import partition_scenarios
    from generator.constants import ALL_SCENARIO_IDS, INTERMEDIATES_DIR, SCENARIOS_OUTPUT_DIR
    from generator.spec_loader import load_spec
    from generator import pipeline
    from generator.types import Pass1Output, Pass2Output
    from qa.qa_validator_types import QAReport

    # Determine scenarios in scope for this phase
    if phase == "pass2":
        # Only correlation scenarios use Pass 2
        try:
            scenario_ids = [
                sid for sid in ALL_SCENARIO_IDS
                if load_spec(sid).pass2_correlations
            ]
        except Exception as e:
            print(f"ERROR loading specs to determine Pass 2 scope: {e}")
            return 2
    else:
        scenario_ids = list(ALL_SCENARIO_IDS)

    # Phase → (checkpoint_phase_name, model_cls_for_validation, runner_fn)
    if phase == "pass1":
        cp_phase, model_cls = "pass1", Pass1Output
        def runner(sid: str) -> None:
            pipeline.run_pass1_for_scenario(sid, intermediates_dir=INTERMEDIATES_DIR)
    elif phase == "pass2":
        cp_phase, model_cls = "pass2", Pass2Output
        def runner(sid: str) -> None:
            pipeline.run_pass2_for_scenario(
                sid,
                scenarios_dir=SCENARIOS_OUTPUT_DIR,
                intermediates_dir=INTERMEDIATES_DIR,
            )
    elif phase == "validate":
        cp_phase, model_cls = "qa_report", QAReport
        def runner(sid: str) -> None:
            pipeline.run_validate_for_scenario(
                sid,
                scenarios_dir=SCENARIOS_OUTPUT_DIR,
                intermediates_dir=INTERMEDIATES_DIR,
            )
    elif phase == "smoke-test":
        from qa.smoke_test import SmokeTestRecommendation
        from qa import smoke_test as st
        cp_phase, model_cls = "smoke_test", SmokeTestRecommendation
        def runner(sid: str) -> None:
            rec = st.generate_smoke_test_recommendation(
                sid, SCENARIOS_OUTPUT_DIR, intermediates_dir=INTERMEDIATES_DIR,
            )
            st.write_smoke_test_recommendation(rec, INTERMEDIATES_DIR)
    elif phase == "smoke-test-judge":
        from qa.smoke_test import SmokeTestJudgeResult, read_smoke_test_recommendation
        from qa import smoke_test as st
        cp_phase, model_cls = "smoke_test_judge", SmokeTestJudgeResult
        def runner(sid: str) -> None:
            rec = read_smoke_test_recommendation(sid, INTERMEDIATES_DIR)
            spec = load_spec(sid)
            result = st.judge_smoke_test_recommendation(sid, rec, spec)
            st.write_smoke_test_judge(result, INTERMEDIATES_DIR)
    elif phase == "build":
        # build-all: run the full pipeline for each scenario, no resume checkpoint
        for sid in scenario_ids:
            print(f"\n=== Building scenario {sid} ===")
            result = pipeline.build_scenario(sid)
            if result.success:
                print(f"  ✓ {sid} ({'QA pass' if result.qa_passed else 'QA fail'})")
            else:
                print(f"  ✗ {sid} failed: {result.error}")
        return 0
    else:
        print(f"ERROR: unknown phase {phase!r}")
        return 2

    # Resume partition
    if force:
        from generator.checkpoint import PhasePartition
        partition = PhasePartition(
            phase=cp_phase, completed=[], remaining=list(scenario_ids),
        )
    else:
        partition = partition_scenarios(
            scenario_ids, cp_phase, INTERMEDIATES_DIR, model_cls=model_cls,
        )

    # Preview
    _print_phase_preview(
        phase, batch=batch,
        completed_count=len(partition.completed),
        remaining_count=len(partition.remaining),
        force=force,
    )

    if partition.all_complete and not force:
        print("✓ Nothing to do — all scenarios already have valid checkpoints.")
        print("  Use --force to re-run all from scratch.")
        return 0

    if not yes:
        if not _confirm():
            print("Aborted.")
            return 1

    if batch:
        os.environ["DATAGEN_BATCH_MODE"] = "true"

    # Run each remaining scenario, checkpointing atomically
    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []
    for sid in partition.remaining:
        print(f"\n  [{sid}] running {phase}...")
        try:
            runner(sid)
            succeeded.append(sid)
            print(f"  [{sid}] ✓ {phase} complete")
        except Exception as e:
            failed.append((sid, str(e)))
            print(f"  [{sid}] ✗ {phase} FAILED: {type(e).__name__}: {e}")

    # Summary
    print()
    print(f"=== Phase {phase} done ===")
    print(f"  Previously complete (skipped): {len(partition.completed)}")
    print(f"  Newly completed this run:      {len(succeeded)}")
    print(f"  Failed this run:               {len(failed)}")
    if failed:
        print()
        print("  Failures:")
        for sid, err in failed:
            print(f"    [{sid}]: {err}")
        return 1
    return 0


def _run_scenario(command: str, args: argparse.Namespace) -> int:
    """Top-level handler for per-scenario commands (build, pass1, pass2, etc.)."""
    scenario_id = args.scenario_id

    from generator.constants import INTERMEDIATES_DIR, SCENARIOS_OUTPUT_DIR
    from generator import pipeline
    from generator.spec_loader import load_spec

    try:
        if command == "build":
            print(f"=== Building scenario {scenario_id} end-to-end ===")
            result = pipeline.build_scenario(scenario_id)
            if not result.success:
                print(f"✗ build failed: {result.error}")
                return 1
            if not result.qa_passed:
                print(f"✗ build complete but QA failed")
                return 1
            print(f"✓ build complete, QA passed → scenarios/{scenario_id}/")
            return 0

        elif command == "build-metadata":
            path = pipeline.run_metadata_for_scenario(scenario_id)
            print(f"✓ Wrote {path}")
            return 0

        elif command == "build-terraform":
            path = pipeline.run_terraform_for_scenario(scenario_id)
            print(f"✓ Wrote {path}")
            return 0

        elif command == "pass1":
            print(f"=== Pass 1 for scenario {scenario_id} ===")
            path = pipeline.run_pass1_for_scenario(scenario_id)
            print(f"✓ Pass 1 complete → {path}")
            return 0

        elif command == "pass2":
            print(f"=== Pass 2 for scenario {scenario_id} ===")
            pass2_path, ce_path = pipeline.run_pass2_for_scenario(scenario_id)
            print(f"✓ Pass 2 complete → {pass2_path}")
            print(f"✓ Correlation evidence → {ce_path}")
            return 0

        elif command == "validate":
            print(f"=== Validating scenario {scenario_id} ===")
            report = pipeline.run_validate_for_scenario(scenario_id)
            print(f"Contract layer: {report.contract_layer.checks_passed}/{report.contract_layer.checks_run} passed")
            print(f"Semantic layer: {report.semantic_layer.checks_passed}/{report.semantic_layer.checks_run} passed")
            print(f"Overall: {report.overall}")
            return 0 if report.overall == "pass" else 1

        elif command == "smoke-test":
            print(f"=== Smoke test (Opus) for scenario {scenario_id} ===")
            from qa import smoke_test as st
            rec = st.generate_smoke_test_recommendation(scenario_id)
            path = st.write_smoke_test_recommendation(rec)
            print(f"✓ Smoke test recommendation → {path}")
            print(f"  finding_type:    {rec.finding_type}")
            print(f"  primary_tier:    {rec.primary_tier}")
            print(f"  action_category: {rec.action_category}")
            print(f"  specific_change: {rec.specific_change[:120]}...")
            return 0

        elif command == "smoke-test-judge":
            print(f"=== Smoke test judge for scenario {scenario_id} ===")
            from qa import smoke_test as st
            rec = st.read_smoke_test_recommendation(scenario_id)
            spec = load_spec(scenario_id)
            result = st.judge_smoke_test_recommendation(scenario_id, rec, spec)
            path = st.write_smoke_test_judge(result)
            print(f"✓ Judge result → {path}")
            print(f"  outcome:         {result.outcome}")
            print(f"  finding_type:    {'✓' if result.finding_type.match else '✗'}")
            print(f"  primary_tier:    {'✓' if result.primary_tier.match else '✗'}")
            print(f"  action_category: {'✓' if result.action_category.match else '✗'}")
            print(f"  specific_change: {'✓' if result.specific_change.match else '✗'}")
            return 0

        else:
            print(f"ERROR: unknown per-scenario command {command!r}")
            return 2

    except Exception as e:
        import traceback
        print(f"✗ {command} failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generator.cli",
        description=(
            "Data-gen pipeline CLI. Use per-scenario commands (pass1, pass2, etc.) "
            "for individual control; use phase-level commands (pass1-all, "
            "pass2-all, etc.) for supervised batch runs with cost preview."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---------- Per-scenario commands ----------
    for cmd, _help in [
        ("build", "Build one scenario end-to-end"),
        ("build-metadata", "Build metadata.json only (Phase A)"),
        ("build-terraform", "Build main.tf only (Phase A)"),
        ("pass1", "Run Pass 1 only"),
        ("pass2", "Run Pass 2 only"),
        ("smoke-test", "Run smoke-test recommendation (Opus) for one scenario"),
        ("smoke-test-judge", "Run judge (Haiku) on saved recommendation for one scenario"),
        ("validate", "Run QA validator without regenerating"),
    ]:
        p = sub.add_parser(cmd, help=_help)
        p.add_argument("scenario_id", help="Zero-padded scenario ID, e.g. '07'.")

    # ---------- Phase-level commands (resumable) ----------
    for cmd, _help in [
        ("pass1-all", "Pass 1 across all 18 scenarios (resumable)"),
        ("pass2-all", "Pass 2 across the 6 correlation scenarios (resumable)"),
        ("validate-all", "QA validator across all 18 (no LLM)"),
        ("smoke-test-all", "Smoke-test recommendation (Opus) on all 18 (resumable)"),
        ("smoke-test-judge-all", "Judge (Haiku) on all saved recommendations (resumable, requires smoke-test-all to have run)"),
        ("build-all", "Full pipeline across all 18 (no per-phase pauses)"),
    ]:
        p = sub.add_parser(cmd, help=_help)
        p.add_argument("--yes", action="store_true",
                       help="Skip the 'Proceed? [y/N]' confirmation prompt.")
        p.add_argument("--batch", action="store_true",
                       help="Submit via Anthropic Batches API (50%% pricing, async).")
        p.add_argument("--force", action="store_true",
                       help="Ignore existing checkpoints; re-run every scenario.")

    args = parser.parse_args(argv)

    # Dispatch
    per_scenario_commands = (
        "build", "build-metadata", "build-terraform",
        "pass1", "pass2", "smoke-test", "smoke-test-judge", "validate",
    )
    phase_commands = (
        "pass1-all", "pass2-all", "smoke-test-all", "smoke-test-judge-all",
        "validate-all", "build-all",
    )
    if args.command in per_scenario_commands:
        return _run_scenario(args.command, args)
    elif args.command in phase_commands:
        # Strip "-all" suffix to get the phase name; build-all becomes "build"
        phase = args.command[:-len("-all")] if args.command.endswith("-all") else args.command
        return _run_phase(phase, args)
    else:
        parser.error(f"unknown command: {args.command}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
