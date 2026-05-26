"""Pipeline-wide constants.

This module mixes two kinds of values:

  1. Architectural constants — hard-coded because they're part of the
     contract (RECORDS_PER_TIER, DATA_WINDOW_START_UTC, INTERVAL_MINUTES,
     ALL_SCENARIO_IDS, file paths). Changing these would break the
     consumer; they should not be runtime-tunable.

  2. Operational parameters — read from environment variables (with
     defaults preserved as fallbacks). These are user-tunable per run:
       - Model assignments (DATAGEN_PASS1_MODEL, etc.)
       - Max output tokens (DATAGEN_PASS1_MAX_TOKENS, etc.)
       - Temperature (DATAGEN_LLM_TEMPERATURE)
       - Retry attempts (DATAGEN_MAX_RETRIES)
       - Batch mode (DATAGEN_BATCH_MODE)

The defaults match the user's decision logged in CHANGELOG: Sonnet 4.6 for
Pass 1 and Pass 2, Opus 4.6 for smoke test recommendation, Haiku 4.5 for
judge. Overriding any default is done by setting the env var in `.env` or
in the shell before invoking the CLI.

To inspect the currently-loaded operational parameters, run:
    uv run python -m generator.cli config
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env at module import time. Idempotent — safe to call multiple times.
load_dotenv()

# ============================================================
# Sampling envelope (per docs/internal/generation-conventions.md §1)
# ============================================================
DATA_WINDOW_START_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
DATA_WINDOW_DAYS = 14
DATA_WINDOW_END_EXCLUSIVE_UTC = datetime(2026, 5, 15, 0, 0, 0, tzinfo=timezone.utc)
INTERVAL_MINUTES = 15
RECORDS_PER_TIER = 1344  # 14 * 96

# ============================================================
# Day mapping (per docs/internal/generation-conventions.md §1)
# 2026-05-01 is a Friday; the window contains 10 weekday dates and 4 weekend dates.
# ============================================================
WEEKDAY_DATES = [
    "2026-05-01", "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07",
    "2026-05-08", "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14",
]
WEEKEND_DATES = ["2026-05-02", "2026-05-03", "2026-05-09", "2026-05-10"]

# ============================================================
# Repository layout
# ============================================================
REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS_DIR = REPO_ROOT / "docs"
DOCS_INTERNAL_DIR = DOCS_DIR / "internal"
SCENARIO_SPECS_DIR = DOCS_INTERNAL_DIR / "scenarios"
HEALTHY_BASELINES_PATH = DOCS_INTERNAL_DIR / "healthy-baselines.md"

PROMPTS_DIR = REPO_ROOT / "prompts"
PASS1_PROMPT_PATH = PROMPTS_DIR / "pass1.txt"
PASS2_PROMPT_PATH = PROMPTS_DIR / "pass2.txt"

SCENARIOS_OUTPUT_DIR = REPO_ROOT / "scenarios"
INTERMEDIATES_DIR = REPO_ROOT / "intermediates"

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# ============================================================
# Scenario IDs (zero-padded strings)
# ============================================================
ALL_SCENARIO_IDS = [f"{i:02d}" for i in range(1, 19)]  # "01" through "18"

# ============================================================
# LLM operational parameters (overridable via .env)
# ============================================================
# All defaults reflect the user's decision logged in CHANGELOG:
#   Pass 1 + Pass 2 → Sonnet 4.6
#   Smoke test       → Opus 4.6
#   Judge            → Haiku 4.5
#
# To override any of these per-run, set the corresponding DATAGEN_* env var
# in .env or in the shell before running the CLI. To inspect what's loaded
# right now, run: `uv run python -m generator.cli config`.

# Model assignments
PASS1_MODEL = os.getenv("DATAGEN_PASS1_MODEL", "claude-sonnet-4-6")
PASS2_MODEL = os.getenv("DATAGEN_PASS2_MODEL", "claude-sonnet-4-6")
SMOKE_TEST_MODEL = os.getenv("DATAGEN_SMOKE_TEST_MODEL", "claude-opus-4-6")
SMOKE_TEST_JUDGE_MODEL = os.getenv(
    "DATAGEN_SMOKE_TEST_JUDGE_MODEL", "claude-haiku-4-5-20251001",
)

# LLM call parameters
LLM_TEMPERATURE = float(os.getenv("DATAGEN_LLM_TEMPERATURE", "0.3"))

# Retry behavior — applies to per-tier Pass 1 and Pass 2 LLM calls.
# Only retries on JSON parse / Pydantic validation / value errors;
# AuthenticationError, RateLimitError, etc. propagate immediately.
MAX_RETRIES = int(os.getenv("DATAGEN_MAX_RETRIES", "3"))

# Max output tokens per LLM call, per phase
# Note: PASS1_MAX_TOKENS is the OLD single-call value, kept for backwards
# compat. The chunked design uses PASS1_CHUNK_MAX_TOKENS (each chunk = 1 day).
PASS1_MAX_TOKENS = int(os.getenv("DATAGEN_PASS1_MAX_TOKENS", "64000"))
PASS2_MAX_TOKENS = int(os.getenv("DATAGEN_PASS2_MAX_TOKENS", "64000"))
SMOKE_TEST_MAX_TOKENS = int(os.getenv("DATAGEN_SMOKE_TEST_MAX_TOKENS", "4096"))
JUDGE_MAX_TOKENS = int(os.getenv("DATAGEN_JUDGE_MAX_TOKENS", "50"))

# Pass 1 day-chunked generation (smooth-generation design):
# Each LLM call produces 96 records (one day) for one tier. 14 chunks per
# tier per scenario. Each chunk fits well within max_tokens with headroom.
PASS1_CHUNK_DAYS = int(os.getenv("DATAGEN_PASS1_CHUNK_DAYS", "1"))     # days per chunk
PASS1_CHUNK_MAX_TOKENS = int(os.getenv("DATAGEN_PASS1_CHUNK_MAX_TOKENS", "16000"))
PASS1_TEMPERATURE = float(os.getenv("DATAGEN_PASS1_TEMPERATURE", "0.2"))
PASS2_TEMPERATURE = float(os.getenv("DATAGEN_PASS2_TEMPERATURE", "0.2"))
INTER_CHUNK_DELAY_SEC = float(os.getenv("DATAGEN_INTER_CHUNK_DELAY_SEC", "0.5"))
CHUNK_RETRY_BACKOFF_SEC = float(os.getenv("DATAGEN_CHUNK_RETRY_BACKOFF_SEC", "2.0"))

# Anthropic SDK-level retry config. Bumped from default (2) to absorb
# transient network blips, 5xx errors, and brief rate-limit windows.
SDK_MAX_RETRIES = int(os.getenv("DATAGEN_SDK_MAX_RETRIES", "5"))

# ---- Pass 2 window-based generation (new architecture) ----
# Each LLM call handles ONE trigger window across all affected tiers.
# Output is small (~10-30 records); fits comfortably in PASS2_WINDOW_MAX_TOKENS.
PASS2_WINDOW_MAX_TOKENS = int(os.getenv("DATAGEN_PASS2_WINDOW_MAX_TOKENS", "8000"))
# Per-window agent loop: max turns of "you failed validation, here's what's wrong, redo"
# feedback before the window is declared unrecoverable and the run aborts.
PASS2_AGENT_MAX_TURNS = int(os.getenv("DATAGEN_PASS2_AGENT_MAX_TURNS", "4"))
# Consecutive trigger windows separated by ≤ this many minutes are merged into
# one work item so the LLM sees the whole event and emits smooth adjustments.
PASS2_MERGE_GAP_MINUTES = int(os.getenv("DATAGEN_PASS2_MERGE_GAP_MINUTES", "30"))
# Per-scenario cost ceiling for Pass 2 (USD). Aborts cleanly with a checkpoint
# in place if exceeded. Set to 0 to disable. Default = generous so quality runs
# don't trip it, but a safety net against runaway agent loops.
PASS2_SCENARIO_MAX_COST_USD = float(os.getenv("DATAGEN_PASS2_SCENARIO_MAX_COST_USD", "50.0"))
# Verification call: every scenario (correlation or not) gets ONE Pass 2 LLM
# call that samples Pass 1 records and confirms plausibility. Removes the
# "no LLM ever" path for non-correlation scenarios. Set to "false" to skip.
PASS2_VERIFICATION_ENABLED = (
    os.getenv("DATAGEN_PASS2_VERIFICATION_ENABLED", "true").lower() in ("true", "1")
)
PASS2_VERIFICATION_MAX_TOKENS = int(os.getenv("DATAGEN_PASS2_VERIFICATION_MAX_TOKENS", "2000"))
# How many records to sample (per active tier) for the verification call.
PASS2_VERIFICATION_SAMPLE_PER_TIER = int(
    os.getenv("DATAGEN_PASS2_VERIFICATION_SAMPLE_PER_TIER", "24")
)

# Batch API toggle (Phase B.6 deliverable)
BATCH_MODE_ENV_VAR = "DATAGEN_BATCH_MODE"
BATCH_MODE_DEFAULT = False


def operational_config_summary() -> dict[str, object]:
    """Return a dict of operational params with current values + sources.

    Used by `cli.py:cmd_config` to print the running configuration.
    """
    def src(env_var: str) -> str:
        return ".env" if os.getenv(env_var) is not None else "(default)"

    return {
        "PASS1_MODEL": (PASS1_MODEL, src("DATAGEN_PASS1_MODEL")),
        "PASS2_MODEL": (PASS2_MODEL, src("DATAGEN_PASS2_MODEL")),
        "SMOKE_TEST_MODEL": (SMOKE_TEST_MODEL, src("DATAGEN_SMOKE_TEST_MODEL")),
        "SMOKE_TEST_JUDGE_MODEL": (SMOKE_TEST_JUDGE_MODEL, src("DATAGEN_SMOKE_TEST_JUDGE_MODEL")),
        "LLM_TEMPERATURE": (LLM_TEMPERATURE, src("DATAGEN_LLM_TEMPERATURE")),
        "PASS1_TEMPERATURE": (PASS1_TEMPERATURE, src("DATAGEN_PASS1_TEMPERATURE")),
        "PASS2_TEMPERATURE": (PASS2_TEMPERATURE, src("DATAGEN_PASS2_TEMPERATURE")),
        "MAX_RETRIES": (MAX_RETRIES, src("DATAGEN_MAX_RETRIES")),
        "SDK_MAX_RETRIES": (SDK_MAX_RETRIES, src("DATAGEN_SDK_MAX_RETRIES")),
        "PASS1_CHUNK_DAYS": (PASS1_CHUNK_DAYS, src("DATAGEN_PASS1_CHUNK_DAYS")),
        "PASS1_CHUNK_MAX_TOKENS": (PASS1_CHUNK_MAX_TOKENS, src("DATAGEN_PASS1_CHUNK_MAX_TOKENS")),
        "PASS2_MAX_TOKENS": (PASS2_MAX_TOKENS, src("DATAGEN_PASS2_MAX_TOKENS")),
        "SMOKE_TEST_MAX_TOKENS": (SMOKE_TEST_MAX_TOKENS, src("DATAGEN_SMOKE_TEST_MAX_TOKENS")),
        "JUDGE_MAX_TOKENS": (JUDGE_MAX_TOKENS, src("DATAGEN_JUDGE_MAX_TOKENS")),
        "INTER_CHUNK_DELAY_SEC": (INTER_CHUNK_DELAY_SEC, src("DATAGEN_INTER_CHUNK_DELAY_SEC")),
        "CHUNK_RETRY_BACKOFF_SEC": (CHUNK_RETRY_BACKOFF_SEC, src("DATAGEN_CHUNK_RETRY_BACKOFF_SEC")),
        "PASS2_WINDOW_MAX_TOKENS": (PASS2_WINDOW_MAX_TOKENS, src("DATAGEN_PASS2_WINDOW_MAX_TOKENS")),
        "PASS2_AGENT_MAX_TURNS": (PASS2_AGENT_MAX_TURNS, src("DATAGEN_PASS2_AGENT_MAX_TURNS")),
        "PASS2_MERGE_GAP_MINUTES": (PASS2_MERGE_GAP_MINUTES, src("DATAGEN_PASS2_MERGE_GAP_MINUTES")),
        "PASS2_SCENARIO_MAX_COST_USD": (PASS2_SCENARIO_MAX_COST_USD, src("DATAGEN_PASS2_SCENARIO_MAX_COST_USD")),
        "PASS2_VERIFICATION_ENABLED": (PASS2_VERIFICATION_ENABLED, src("DATAGEN_PASS2_VERIFICATION_ENABLED")),
        "PASS2_VERIFICATION_MAX_TOKENS": (PASS2_VERIFICATION_MAX_TOKENS, src("DATAGEN_PASS2_VERIFICATION_MAX_TOKENS")),
        "PASS2_VERIFICATION_SAMPLE_PER_TIER": (
            PASS2_VERIFICATION_SAMPLE_PER_TIER,
            src("DATAGEN_PASS2_VERIFICATION_SAMPLE_PER_TIER"),
        ),
        "DATAGEN_BATCH_MODE": (
            os.getenv("DATAGEN_BATCH_MODE", "false").lower() in ("true", "1"),
            src("DATAGEN_BATCH_MODE"),
        ),
    }
