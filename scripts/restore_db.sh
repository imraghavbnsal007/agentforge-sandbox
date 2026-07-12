#!/usr/bin/env bash
# Restore the AgentForge PostgreSQL database from a backups/*.sql dump.
#
# Usage: scripts/restore_db.sh backups/agentforge-YYYYMMDD-HHMMSS.sql
#
# Honors COMPOSE_PROJECT_NAME (isolated stacks restore into their own DB).
#
# Steps:
#   1. validate the dump file (exists, non-trivial size, pg_dump header)
#   2. automatic pre-restore safety backup (auto-agentforge-*.sql)
#   3. stop backend + worker so nothing writes mid-restore
#   4. clean restore: drop + recreate the public schema, load the dump
#   5. alembic upgrade head (applies migrations newer than the dump)
#   6. row-count summary, then restart backend + worker
#
# This script never deletes Docker volumes.

set -euo pipefail

cd "$(dirname "$0")/.."

DB_USER="agentforge"
DB_NAME="agentforge"
MIN_BYTES=512

FILE="${1:-}"
if [[ -z "$FILE" ]]; then
    echo "Usage: scripts/restore_db.sh backups/<backup>.sql" >&2
    exit 1
fi
if [[ ! -f "$FILE" ]]; then
    echo "ERROR: $FILE does not exist." >&2
    exit 1
fi
SIZE=$(wc -c < "$FILE" | tr -d ' ')
if [[ "$SIZE" -lt "$MIN_BYTES" ]]; then
    echo "ERROR: $FILE is only ${SIZE} bytes — not a plausible dump." >&2
    exit 1
fi
if ! head -20 "$FILE" | grep -q "PostgreSQL database dump"; then
    echo "ERROR: $FILE does not look like pg_dump output." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running." >&2
    exit 1
fi
if ! docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
    echo "ERROR: the postgres service is not running." >&2
    exit 1
fi

echo "==> Pre-restore safety backup"
scripts/backup_db.sh --auto

# Only stop/start app services that actually have containers — an isolated
# test stack may run postgres alone.
APP_CONTAINERS="$(docker compose ps -q backend worker 2>/dev/null || true)"

if [[ -n "$APP_CONTAINERS" ]]; then
    echo "==> Stopping backend and worker"
    docker compose stop backend worker
fi

echo "==> Clean restore of $FILE (${SIZE} bytes)"
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    < "$FILE" > /dev/null

echo "==> Applying migrations (alembic upgrade head)"
docker compose run --rm --no-deps backend alembic upgrade head

echo "==> Row counts"
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "
  SELECT relname AS table, n_live_tup AS approx_rows
  FROM pg_stat_user_tables ORDER BY relname;"

if [[ -n "$APP_CONTAINERS" ]]; then
    echo "==> Restarting backend and worker"
    docker compose start backend worker
fi

echo "Restore complete."
