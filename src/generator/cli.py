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

    Resume-aware. Steps:

      1. Scan `intermediates/NN/<phase>.json` to determine which scenarios
         already have valid checkpoints (use `checkpoint.partition_scenarios`).
      2. If --force, ignore checkpoints — re-run all scenarios.
      3. Print phase preview with resume reflection:
            "Already complete: 12 (skipped)"
            "Remaining to run:  6"
            "Estimated cost:    ~$X (pro-rated)"
      4. Unless --yes, ask for confirmation. If remaining=0, skip the prompt
         and exit cleanly.
      5. If --batch, set DATAGEN_BATCH_MODE=true for this process.
      6. Dispatch to the phase implementation in pipeline.py / smoke_test.py.
         The dispatched function MUST itself use the same resume pattern —
         this is defense in depth.
      7. Print final summary (per-scenario success/fail + total cost + wall time).

    Recovery semantics: each scenario's output is written atomically to
    `intermediates/NN/<phase>.json` after the LLM call returns successfully.
    A SIGINT, Mac sleep, or crash during scenario K loses only scenario K's
    work — scenarios 1..K-1 are durable. Re-running this command resumes
    from K. No double-billing on completed scenarios.
    """
    batch = getattr(args, "batch", False)
    force = getattr(args, "force", False)
    yes = getattr(args, "yes", False)

    raise NotImplementedError(
        f"Phase B/C — wire `{phase}` with the resume pattern below. "
        f"This shape is concrete; only the per-scenario function is a stub.\n"
        f"\n"
        f"    from generator.checkpoint import partition_scenarios\n"
        f"    from generator.constants import ALL_SCENARIO_IDS, INTERMEDIATES_DIR\n"
        f"    # phase → (model_cls, run_fn) — model_cls validates the checkpoint\n"
        f"    PHASE_DISPATCH = {{\n"
        f"        'pass1':            (Pass1Output,             pipeline.run_pass1_for_scenario),\n"
        f"        'pass2':            (Pass2Output,             pipeline.run_pass2_for_scenario),\n"
        f"        'validate':         (QAReport,                pipeline.run_validate_for_scenario),\n"
        f"        'smoke-test':       (SmokeTestRecommendation, smoke_test.generate_smoke_test_recommendation),\n"
        f"        'smoke-test-judge': (SmokeTestJudgeResult,    smoke_test.judge_smoke_test_recommendation),\n"
        f"    }}\n"
        f"    model_cls, run_fn = PHASE_DISPATCH['{phase}']\n"
        f"    scenario_ids = ... # filter by phase (Pass 2 only correlation scenarios)\n"
        f"    if force:\n"
        f"        partition = PhasePartition(phase='{phase}', completed=[], remaining=scenario_ids)\n"
        f"    else:\n"
        f"        partition = partition_scenarios(scenario_ids, '{phase}', INTERMEDIATES_DIR, model_cls)\n"
        f"    _print_phase_preview('{phase}', batch=batch,\n"
        f"                         completed_count=len(partition.completed),\n"
        f"                         remaining_count=len(partition.remaining),\n"
        f"                         force=force)\n"
        f"    if partition.all_complete and not force:\n"
        f"        print('✓ Nothing to do.'); return 0\n"
        f"    if not yes and not _confirm():\n"
        f"        print('Aborted.'); return 1\n"
        f"    if batch:\n"
        f"        os.environ['DATAGEN_BATCH_MODE'] = 'true'\n"
        f"    # Run only the remaining scenarios; checkpoint each one as it completes.\n"
        f"    for sid in partition.remaining:\n"
        f"        result = run_fn(sid, ...)\n"
        f"        write_pydantic_atomic(checkpoint_path(sid, '{phase}', INTERMEDIATES_DIR), result)\n"
        f"        print(f'  [{{sid}}] ✓ {{phase}} complete')\n"
        f"    print(f'\\nPhase {phase} done. {{len(partition.remaining)}} new scenarios completed.')\n"
        f"    return 0"
    )


def _run_scenario(phase: str, args: argparse.Namespace) -> int:
    """Top-level handler for per-scenario commands (build, pass1, pass2, etc.)."""
    raise NotImplementedError(
        f"Phase A/B — wire `{phase}` for scenario {args.scenario_id} to its "
        f"pipeline implementation. See BUILD_PLAN.md for the phase mapping."
    )


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
