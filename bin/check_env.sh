#!/usr/bin/env bash
# ============================================================
# check_env.sh — Validate .env contents without exposing values.
#
# Checks:
#   - ANTHROPIC_API_KEY is set
#   - ANTHROPIC_API_KEY length is plausible (real keys are ~108 chars)
#   - ANTHROPIC_API_KEY starts with sk-ant-
#   - ANTHROPIC_API_KEY does NOT match known placeholder patterns
#   - LANGSMITH_API_KEY length is plausible (if LANGSMITH_TRACING=true)
#
# Run this BEFORE any expensive run to catch a stale or placeholder key
# before you spend money on a 401-erroring API call.
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed (prints diagnostics, redacts values)
# ============================================================

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

uv run python3 <<'PYEOF'
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env explicitly from the current working directory (the repo root,
# since the wrapping bash script `cd`s there). Using an explicit path avoids
# dotenv's stack-frame-walking auto-discovery, which fails inside heredocs.
load_dotenv(Path.cwd() / ".env")

errors = []
warnings = []

# ----- ANTHROPIC_API_KEY (REQUIRED) -----
key = os.getenv("ANTHROPIC_API_KEY", "")
if not key:
    errors.append("ANTHROPIC_API_KEY is not set in .env")
elif len(key) < 50:
    errors.append(
        f"ANTHROPIC_API_KEY is suspiciously short ({len(key)} chars). "
        f"Real Anthropic keys are ~108 chars. Likely a placeholder."
    )
elif not key.startswith("sk-ant-"):
    errors.append(
        f"ANTHROPIC_API_KEY does not start with 'sk-ant-'. "
        f"Got prefix: {key[:8]!r}. Not an Anthropic key."
    )
elif key in ("sk-ant-real-secret-key", "sk-ant-your-key-here"):
    errors.append("ANTHROPIC_API_KEY is a known placeholder, not a real key.")

# ----- LANGSMITH (optional) -----
tracing = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1")
if tracing:
    ls_key = os.getenv("LANGSMITH_API_KEY", "")
    if not ls_key:
        errors.append("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is not set")
    elif len(ls_key) < 30:
        errors.append(
            f"LANGSMITH_API_KEY is suspiciously short ({len(ls_key)} chars). "
            f"Real LangSmith keys are typically 50+ chars."
        )

    ls_project = os.getenv("LANGSMITH_PROJECT", "")
    if not ls_project:
        warnings.append("LANGSMITH_PROJECT is not set; traces will land in the default project")

# ----- Report -----
print("=== .env sanity check ===")
if not key:
    print("  ANTHROPIC_API_KEY:    NOT SET")
else:
    masked = key[:13] + "..." + key[-4:] if len(key) > 20 else key
    print(f"  ANTHROPIC_API_KEY:    {masked}  ({len(key)} chars)")

if tracing:
    ls_key = os.getenv("LANGSMITH_API_KEY", "")
    masked = ls_key[:6] + "..." + ls_key[-4:] if len(ls_key) > 12 else (ls_key or "(unset)")
    print(f"  LANGSMITH_API_KEY:    {masked}  ({len(ls_key)} chars)")
    print(f"  LANGSMITH_PROJECT:    {os.getenv('LANGSMITH_PROJECT', '(unset)')}")
else:
    print(f"  LANGSMITH_TRACING:    disabled")
print()

if errors:
    print("✗ FAILED — fix the following before running any paid commands:")
    for e in errors:
        print(f"    • {e}")
    print()
    print("  To update .env without exposing values, use your editor:")
    print("    nano .env  (or code .env, vim .env, etc.)")
    sys.exit(1)

if warnings:
    print("⚠ WARNINGS (non-fatal):")
    for w in warnings:
        print(f"    • {w}")
    print()

print("✓ .env appears valid. Safe to run paid commands.")
PYEOF
