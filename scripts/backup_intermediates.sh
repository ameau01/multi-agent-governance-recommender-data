#!/usr/bin/env bash
# ============================================================
# backup_intermediates.sh — Snapshot intermediates/ to .workspace/
#
# Creates a timestamped tar.gz archive under .workspace/ so that
# remediation work on Pass 1 / Pass 2 / validator can be done
# without fear of losing the current working state.
#
# .workspace/ is in .gitignore so the backups stay local.
#
# Usage:
#   scripts/backup_intermediates.sh
#       Create a new backup. Doesn't touch existing backups.
#   scripts/backup_intermediates.sh --retain 5
#       Create a backup, then keep only the newest 5 backups
#       (delete older ones).
#   scripts/backup_intermediates.sh --list
#       Show existing backups in .workspace/, do nothing else.
#   scripts/backup_intermediates.sh -h | --help
#       This message.
#
# To restore from a backup, see the post-backup output for
# the exact tar commands.
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RETAIN=0
LIST_ONLY=0

show_help() {
  sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'
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
  echo "Existing backups in .workspace/:"
  if compgen -G ".workspace/intermediates_backup_*.tar.gz" > /dev/null; then
    ls -lh .workspace/intermediates_backup_*.tar.gz | awk '{printf "  %s  %s  %s %s %s\n", $5, $NF, $6, $7, $8}'
  else
    echo "  (none yet)"
  fi
  exit 0
fi

# ---- Sanity ----
if [[ ! -d intermediates ]]; then
  echo "ERROR: intermediates/ does not exist — nothing to back up" >&2
  exit 1
fi

# ---- Create backup ----
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP=".workspace/intermediates_backup_${TIMESTAMP}.tar.gz"

SRC_SIZE=$(du -sh intermediates/ | awk '{print $1}')

echo "Creating backup of intermediates/ ..."
echo "  Source : intermediates/   ($SRC_SIZE uncompressed)"
echo "  Target : $BACKUP"

tar -czf "$BACKUP" intermediates/

DEST_SIZE=$(du -sh "$BACKUP" | awk '{print $1}')
echo "  ✓ done — compressed size: $DEST_SIZE"

# ---- Rotation ----
if [[ "$RETAIN" -gt 0 ]]; then
  echo ""
  echo "Rotating: keeping newest $RETAIN backup(s)"
  TO_DELETE=$(ls -1t .workspace/intermediates_backup_*.tar.gz 2>/dev/null | tail -n +"$((RETAIN + 1))" || true)
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
echo "All backups in .workspace/:"
ls -lh .workspace/intermediates_backup_*.tar.gz 2>/dev/null | awk '{printf "  %s  %s\n", $5, $NF}'

cat <<EOF

To restore from this backup later:

  # 1. List contents without extracting (non-destructive)
  tar -tzf "$BACKUP" | head -20

  # 2. Extract a single scenario into a sibling folder (non-destructive)
  mkdir -p .workspace/restore_test
  tar -xzf "$BACKUP" -C .workspace/restore_test intermediates/01

  # 3. FULL restore — OVERWRITES current intermediates/ (use with care)
  tar -xzf "$BACKUP"
EOF
