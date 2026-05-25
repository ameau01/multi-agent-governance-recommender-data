"""CLI entry point for the data-gen pipeline.

# Per-scenario commands (individual control)

    python -m generator.cli build NN               Build one scenario end-to-end.
    python -m generator.cli build-metadata NN      Phase A: metadata only, no telemetry.
    python -m generator.cli build-terraform NN     Phase A: main.tf only.
    python -m generator.cli pass1 NN               Phase B: regenerate Pass 1 only.
    python -m generator.cli pass2 NN               Phase B: regenerate Pass 2 only.
    python -m generator.cli validate NN            Run QA validator without regenerating.
    python -m generator.cli smoke-test NN          Run smoke test for one scenario.

# Phase-level commands (manual oversight across all scenarios)

These print cost + time estimates, ask for confirmation, then run the phase
across the relevant scenarios. Use these for the supervised pipeline run.

    python -m generator.cli pass1-all              Pass 1 for all 18 scenarios.
    python -m generator.cli pass2-all              Pass 2 for the ~6 correlation scenarios.
    python -m generator.cli validate-all           QA validator across all 18.
    python -m generator.cli smoke-test-all         Smoke test (Opus + Haiku judge) on all 18.
    python -m generator.cli build-all              Full pipeline on all 18 (no per-phase pauses).

# Flags

    --yes          Skip the "Proceed? [y/N]" confirmation prompt (for scripts/CI).
    --batch        Submit via Anthropic Batches API (50% pricing, ~5-30 min wall time).
                   Sets DATAGEN_BATCH_MODE=true for this invocation.

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
# Cost + time estimates per phase (for the confirmation prompt)
# Numbers from BUILD_PLAN.md "Model strategy and cost" section.
# Sonnet/Opus pricing, with prompt caching enabled.
# ============================================================
PHASE_ESTIMATES = {
    "pass1": {
        "scenarios": 18,
        "model": "claude-sonnet-4-6",
        "cost_estimate_usd": 101.0,
        "cost_estimate_batch_usd": 50.5,
        "wall_time_estimate_min_interactive": 15,
        "wall_time_estimate_min_batch": 30,
    },
    "pass2": {
        "scenarios": 6,                              # only correlation scenarios use Pass 2
        "model": "claude-sonnet-4-6",
        "cost_estimate_usd": 54.0,
        "cost_estimate_batch_usd": 27.0,
        "wall_time_estimate_min_interactive": 8,
        "wall_time_estimate_min_batch": 20,
    },
    "smoke-test": {
        "scenarios": 18,
        "model": "claude-opus-4-6 (judge: claude-haiku-4-5-20251001)",
        "cost_estimate_usd": 1.45,
        "cost_estimate_batch_usd": 0.73,
        "wall_time_estimate_min_interactive": 6,
        "wall_time_estimate_min_batch": 15,
    },
    "validate": {
        "scenarios": 18,
        "model": "(none — deterministic checks, no LLM)",
        "cost_estimate_usd": 0.0,
        "cost_estimate_batch_usd": 0.0,
        "wall_time_estimate_min_interactive": 1,
        "wall_time_estimate_min_batch": 1,
    },
}


def _print_phase_preview(phase: str, batch: bool) -> None:
    """Print what's about to happen, cost + time estimates."""
    est = PHASE_ESTIMATES[phase]
    mode = "BATCH (50% pricing, async)" if batch else "INTERACTIVE (full pricing, sync)"
    cost = est["cost_estimate_batch_usd"] if batch else est["cost_estimate_usd"]
    wall_time = (
        est["wall_time_estimate_min_batch"]
        if batch
        else est["wall_time_estimate_min_interactive"]
    )
    print(f"=== Phase: {phase} ===")
    print(f"  Scenarios:       {est['scenarios']}")
    print(f"  Model:           {est['model']}")
    print(f"  Mode:            {mode}")
    print(f"  Estimated cost:  ~${cost:.2f}")
    print(f"  Estimated time:  ~{wall_time} minutes")
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

    Steps:
      1. Print phase preview (scenarios, model, cost, time estimates).
      2. Unless --yes, ask for confirmation.
      3. If --batch, set DATAGEN_BATCH_MODE=true for this process.
      4. Dispatch to the phase implementation in pipeline.py.
      5. Print final summary (per-scenario success/fail + total cost + wall time).

    Phase implementation is in `pipeline.py` and is filled in during Phase B/C.
    """
    batch = getattr(args, "batch", False)
    _print_phase_preview(phase, batch=batch)
    if not getattr(args, "yes", False):
        if not _confirm():
            print("Aborted.")
            return 1
    if batch:
        os.environ["DATAGEN_BATCH_MODE"] = "true"

    raise NotImplementedError(
        f"Phase B/C — wire `{phase}` to its pipeline implementation. "
        f"Reference: import from generator.pipeline and dispatch:\n"
        f"  pass1-all      → pipeline.build_phase_for_all('pass1', batch=batch)\n"
        f"  pass2-all      → pipeline.build_phase_for_all('pass2', batch=batch)\n"
        f"  smoke-test-all → pipeline.build_phase_for_all('smoke_test', batch=batch)\n"
        f"  validate-all   → pipeline.validate_all_scenarios()\n"
        f"After running, print a summary table with per-scenario status."
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
        ("smoke-test", "Run smoke test for one scenario"),
        ("validate", "Run QA validator without regenerating"),
    ]:
        p = sub.add_parser(cmd, help=_help)
        p.add_argument("scenario_id", help="Zero-padded scenario ID, e.g. '07'.")

    # ---------- Phase-level commands ----------
    for cmd, _help in [
        ("pass1-all", "Pass 1 across all 18 scenarios (with cost preview + confirmation)"),
        ("pass2-all", "Pass 2 across the 6 correlation scenarios (with cost preview + confirmation)"),
        ("smoke-test-all", "Smoke test across all 18 (with cost preview + confirmation)"),
        ("validate-all", "QA validator across all 18 (no LLM, no confirmation)"),
        ("build-all", "Full pipeline across all 18 (no per-phase pauses)"),
    ]:
        p = sub.add_parser(cmd, help=_help)
        p.add_argument("--yes", action="store_true",
                       help="Skip the 'Proceed? [y/N]' confirmation prompt.")
        p.add_argument("--batch", action="store_true",
                       help="Submit via Anthropic Batches API (50%% pricing, async).")

    args = parser.parse_args(argv)

    # Dispatch
    if args.command in ("build", "build-metadata", "build-terraform",
                        "pass1", "pass2", "smoke-test", "validate"):
        return _run_scenario(args.command, args)
    elif args.command in ("pass1-all", "pass2-all", "smoke-test-all",
                          "validate-all", "build-all"):
        # Strip "-all" suffix for the phase name; build-all becomes "build"
        phase = args.command[:-len("-all")] if args.command.endswith("-all") else args.command
        return _run_phase(phase, args)
    else:
        parser.error(f"unknown command: {args.command}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
