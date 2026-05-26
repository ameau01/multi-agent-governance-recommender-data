#!/usr/bin/env bash
# ============================================================
# backup_all_outputs.sh — Snapshot all pipeline outputs (success
# AND failure) to .workspace/.
#
# Covers three directories:
#   - intermediates/   Pass 1 / Pass 2 / smoke-test / judge artifacts
#                      and per-scenario LLM logs.
#   - scenarios/       Splitter outputs (tier telemetry files,
#                      metadata.json, main.tf, correlation_evidence.json).
#   - logs/            Full run-log audit trail (per-phase + sweep).
#
# DOES NOT include:
#   - export/          Derivative; rebuild from scenarios/ via
#                      scripts/export_passing_scenarios.sh.
#   - .workspace/      Where the backups themselves live.
#   - source code      Tracked in git; restore via git checkout.
#   - .env             Never touched.
#
# .workspace/ is gitignored so the backups stay local.
#
# Usage:
#   scripts/backup_all_outputs.sh
#       Create a new backup. Doesn't touch existing backups.
#   scripts/backup_all_outputs.sh --retain 5
#       Create a backup, then keep only the newest 5 (delete older).
#   scripts/backup_all_outputs.sh --list
#       Show existing all-outputs backups, do nothing else.
#   scripts/backup_all_outputs.sh -h | --help
#       This message.
#
# To restore from a backup, see the post-backup output for the
# exact tar commands.
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Directories to include in the snapshot, in scan order.
# (Each is included only if it exists on disk.)
INCLUDE_DIRS=(intermediates scenarios logs)

RETAIN=0
LIST_ONLY=0

show_help() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --retain)
      [[ $# -ge 2 ]] || { echo "ERROR: --retain needs an integer" >&2; exit 2; }
      RETAIN="$2"
      [[ "$RETAIN" =~ ^[0-9]+$ ]] || {
        echo "ERROR: --retain must be a non-negative integer (got '$RETAIN')" >&2
        exit 2
      }
      shift 2 ;;
    --list) LIST_ONLY=1; shift ;;
    *) echo "ERROR: unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done

mkdir -p .workspace

# ---- --list short-circuit ----
if [[ "$LIST_ONLY" == "1" ]]; then
  echo "Existing all-outputs backups in .workspace/:"
  if compgen -G ".workspace/all_outputs_backup_*.tar.gz" > /dev/null; then
    ls -lh .workspace/all_outputs_backup_*.tar.gz | awk '{printf "  %s  %s\n", $5, $NF}'
  else
    echo "  (none yet)"
  fi
  exit 0
fi

# ---- Pick which top-level dirs actually exist ----
EXISTING=()
MISSING=()
for d in "${INCLUDE_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    EXISTING+=("$d")
  else
    MISSING+=("$d")
  fi
done

if [[ "${#EXISTING[@]}" -eq 0 ]]; then
  echo "ERROR: none of {${INCLUDE_DIRS[*]}} exist — nothing to back up" >&2
  exit 1
fi

# ---- Create backup ----
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP=".workspace/all_outputs_backup_${TIMESTAMP}.tar.gz"

echo "Creating full pipeline-output backup ..."
echo "  Included directories:"
for d in "${EXISTING[@]}"; do
  sz=$(du -sh "$d" 2>/dev/null | awk '{print $1}')
  printf "    %-18s (%s uncompressed)\n" "$d" "$sz"
done
if [[ "${#MISSING[@]}" -gt 0 ]]; then
  echo "  Skipped (not present):"
  for d in "${MISSING[@]}"; do
    printf "    %-18s (not on disk)\n" "$d"
  done
fi
echo "  Target : $BACKUP"

tar -czf "$BACKUP" "${EXISTING[@]}"

DEST_SIZE=$(du -sh "$BACKUP" | awk '{print $1}')
echo "  ✓ done — compressed size: $DEST_SIZE"

# ---- Rotation ----
if [[ "$RETAIN" -gt 0 ]]; then
  echo ""
  echo "Rotating: keeping newest $RETAIN all-outputs backup(s)"
  TO_DELETE=$(ls -1t .workspace/all_outputs_backup_*.tar.gz 2>/dev/null | tail -n +"$((RETAIN + 1))" || true)
  if [[ -z "$TO_DELETE" ]]; then
    echo "  (nothing to delete — fewer than $RETAIN backups exist)"
  else
    while IFS= read -r old; do
      [[ -z "$old" ]] && continue
      echo "  - removing old backup: $old"
      rm -f "$old"
    done <<< "$TO_DELETE"
  fi
fi

# ---- Report ----
echo ""
echo "All all-outputs backups in .workspace/:"
ls -lh .workspace/all_outputs_backup_*.tar.gz 2>/dev/null | awk '{printf "  %s  %s\n", $5, $NF}'

cat <<EOF

To restore from this backup later:

  # 1. List contents without extracting (non-destructive)
  tar -tzf "$BACKUP" | head -30

  # 2. Extract ONE scenario's intermediates into a sibling folder (non-destructive)
  mkdir -p .workspace/restore_test
  tar -xzf "$BACKUP" -C .workspace/restore_test intermediates/01

  # 3. Extract one whole top-level dir to a sibling (non-destructive)
  mkdir -p .workspace/restore_test
  tar -xzf "$BACKUP" -C .workspace/restore_test scenarios

  # 4. FULL restore — OVERWRITES current intermediates/, scenarios/, logs/ (use with care)
  tar -xzf "$BACKUP"
EOF
