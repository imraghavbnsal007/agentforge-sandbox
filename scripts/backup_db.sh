#!/usr/bin/env bash
# Back up the AgentForge PostgreSQL database to backups/*.sql.
#
# Usage:
#   scripts/backup_db.sh          -> backups/agentforge-YYYYMMDD-HHMMSS.sql
#   scripts/backup_db.sh --auto   -> backups/auto-agentforge-YYYYMMDD-HHMMSS.sql
#                                    (safety backups; only the latest 10 are kept)
#
# Honors COMPOSE_PROJECT_NAME, so an isolated test stack
# (COMPOSE_PROJECT_NAME=agentforge_bktest) backs up its own database.
#
# Safety properties:
#   - writes to a temp file, validates it, then atomically renames
#   - never overwrites an existing backup
#   - never deletes manual backups; retention applies to auto-* only

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="backups"
DB_USER="agentforge"
DB_NAME="agentforge"
KEEP_AUTO=10
MIN_BYTES=512   # a valid dump of even an empty schema is bigger than this

PREFIX="agentforge"
if [[ "${1:-}" == "--auto" ]]; then
    PREFIX="auto-agentforge"
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running." >&2
    exit 1
fi

if ! docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
    echo "ERROR: the postgres service is not running (docker compose ps)." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)"
FINAL="$BACKUP_DIR/$PREFIX-$STAMP.sql"
TMP="$BACKUP_DIR/.$PREFIX-$STAMP.sql.tmp"

if [[ -e "$FINAL" ]]; then
    echo "ERROR: $FINAL already exists — refusing to overwrite." >&2
    exit 1
fi

cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" > "$TMP"

SIZE=$(wc -c < "$TMP" | tr -d ' ')
if [[ "$SIZE" -lt "$MIN_BYTES" ]]; then
    echo "ERROR: dump is only ${SIZE} bytes — refusing to keep it." >&2
    exit 1
fi
if ! head -20 "$TMP" | grep -q "PostgreSQL database dump"; then
    echo "ERROR: dump does not look like pg_dump output — refusing to keep it." >&2
    exit 1
fi

mv "$TMP" "$FINAL"
trap - EXIT
echo "Backup written: $FINAL (${SIZE} bytes)"

# Retention: keep the newest $KEEP_AUTO auto backups. Manual backups
# (no auto- prefix) are never touched.
if [[ "$PREFIX" == "auto-agentforge" ]]; then
    ls -1t "$BACKUP_DIR"/auto-agentforge-*.sql 2>/dev/null \
        | tail -n +"$((KEEP_AUTO + 1))" \
        | while IFS= read -r old; do
            rm -f "$old"
            echo "Pruned old auto backup: $old"
        done
fi
