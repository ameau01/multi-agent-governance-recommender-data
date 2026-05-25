"""Pipeline-wide constants.

The sampling envelope and the day-mapping are fixed for the v1.0.0 contract.
See `docs/internal/generation-conventions.md` §1 for the canonical definitions.
"""

from datetime import datetime, timezone
from pathlib import Path

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
# LLM configuration
# ============================================================
# Model selection rationale (see BUILD_PLAN.md "Model strategy and cost" for
# the full comparison):
#
#   Pass 1 → Sonnet 4.6     Telemetry generation needs reliable adherence to
#                           ranges, time patterns, and the 11-of-14 rule. Sonnet's
#                           instruction-following reduces Phase B iteration count
#                           vs. Haiku, paying for itself in fewer prompt-tuning
#                           cycles. ~$101 of the build budget.
#
#   Pass 2 → Sonnet 4.6     Pass 2 invariance (preserving Pass 1 bit-exact outside
#                           correlation windows) demands precise rule-following on
#                           large JSON inputs. Sonnet is the right tier here;
#                           Haiku is too risky on invariance, Opus is overkill.
#                           ~$54 of the build budget (with prompt caching).
#
#   Smoke test → Opus 4.6   Strongest available baseline check. If even Opus can't
#                           solve a scenario in one call, the multi-agent system's
#                           depth is genuinely needed (positive design signal).
#                           ~$1.45 of the build budget — incremental cost over
#                           Sonnet is trivial (~$0.58).
#
#   Judge → Haiku 4.5       One-line "substantively the same change? YES/NO".
#                           Trivial reasoning, trivial cost. ~$0.01.
#
# Estimated total (with caching, no Batch API): ~$157 against $150 credit.
# Estimated total (with caching + Batch API):   ~$79 — recommended path.
# Set BATCH_MODE_ENV_VAR (DATAGEN_BATCH_MODE=true) to opt into Batch API once
# Phase B.6 implements the batch code path.

PASS1_MODEL = "claude-sonnet-4-6"
PASS2_MODEL = "claude-sonnet-4-6"
SMOKE_TEST_MODEL = "claude-opus-4-6"
SMOKE_TEST_JUDGE_MODEL = "claude-haiku-4-5-20251001"
LLM_TEMPERATURE = 0.3

# Batch API configuration — applied once the batch code path lands (Phase B.6).
# When BATCH_MODE_ENV_VAR is "true", the pipeline submits LLM calls via
# Anthropic's Batches API at 50% of standard pricing. The 18-scenario build is
# an asynchronous batch workload by nature (not interactive), so this is a
# near-pure cost win. See BUILD_PLAN.md for the Phase B.6 task.
BATCH_MODE_ENV_VAR = "DATAGEN_BATCH_MODE"
BATCH_MODE_DEFAULT = False
