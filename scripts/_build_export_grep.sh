#!/usr/bin/env bash
# Banned-word grep for public-export/. Exits non-zero if any forbidden string
# is found anywhere in the target tree. Used by build_public_export.sh.

set -uo pipefail

TARGET="${1:-public-export}"
if [[ ! -d "$TARGET" ]]; then
  echo "ERROR: target dir not found: $TARGET" >&2
  exit 2
fi

# Forbidden strings (case-insensitive). Each line is one substring to ban.
# Provenance + model names
BANNED_PROVENANCE=(
  "claude-opus"
  "claude-sonnet"
  "claude-haiku"
  "anthropic"
  "langsmith"
  "raw_model_response"
  "smoke_test_judge"
  "smoke_test_llm_log"
  "pass1_llm_log"
  "pass2_llm_log"
  "target_recommendation"
)

# Voice-rule banned words (per DECISIONS.md section 6). Match whole words
# only — substrings would have too many false positives ("foster" in
# "fostering" is fine inside a code comment we accept, but the standalone
# word in prose is not).
BANNED_VOICE=(
  "delve"
  "tapestry"
  "embark"
  "harness"
  "robust"
  "comprehensive"
  "seamless"
  "intricate"
  "nuanced"
  "underscore"
  "pivotal"
  "paramount"
  "in the realm of"
  "it is worth noting"
  "plays a crucial role"
  "foster "
  "illuminate"
)

# Files where voice rules don't apply (per DECISIONS.md):
#   design/ (internal design log)
#   *.tf (terraform may contain AWS service names like 'aws_lb_robust' if any)
#   *.json (data files; AWS terms allowed)
# But provenance bans apply EVERYWHERE.
VOICE_GLOB_EXCLUDE=(
  --exclude-dir=design
  --include="*.md"
  --include="*.py"
)

FAIL_COUNT=0

echo "  Checking provenance bans across $TARGET..."
for needle in "${BANNED_PROVENANCE[@]}"; do
  if grep -ril --binary-files=without-match "$needle" "$TARGET" >/dev/null 2>&1; then
    # Allow design/DECISIONS.md to mention these in context of WHAT is banned
    HITS=$(grep -ril --binary-files=without-match "$needle" "$TARGET" \
           | grep -v "design/DECISIONS.md" || true)
    if [[ -n "$HITS" ]]; then
      echo "  ✗ FORBIDDEN STRING: \"$needle\""
      echo "$HITS" | sed 's/^/      /'
      FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
  fi
done

echo "  Checking voice bans in README/EVAL/DATASET_CARD markdown..."
for needle in "${BANNED_VOICE[@]}"; do
  HITS=$(grep -ril --binary-files=without-match \
         "${VOICE_GLOB_EXCLUDE[@]}" \
         "$needle" "$TARGET" 2>/dev/null | grep -v "design/" || true)
  if [[ -n "$HITS" ]]; then
    echo "  ✗ BANNED VOICE WORD: \"$needle\""
    echo "$HITS" | sed 's/^/      /'
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo ""
  echo "  ✗ $FAIL_COUNT sanitization violation(s). Fix before publishing."
  exit 1
fi
echo "  ✓ all banned-word checks passed"
exit 0
