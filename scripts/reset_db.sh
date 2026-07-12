#!/usr/bin/env bash
# PERMANENTLY DELETE the AgentForge database volume.
#
# This is the ONLY place in the repository allowed to run
# `docker compose down -v`. It requires typing an exact confirmation
# phrase and takes an automatic safety backup first.
#
# Honors COMPOSE_PROJECT_NAME (an isolated test stack resets only itself).

set -euo pipefail

cd "$(dirname "$0")/.."

CONFIRM_PHRASE="DELETE ALL AGENTFORGE DATA"

echo ""
echo "⚠️  This PERMANENTLY deletes the PostgreSQL volume for compose project"
echo "   '${COMPOSE_PROJECT_NAME:-agentforge (default)}' — all projects, tasks,"
echo "   analyses, and run history."
echo ""
echo "Type exactly:  $CONFIRM_PHRASE"
printf "> "
read -r REPLY
if [[ "$REPLY" != "$CONFIRM_PHRASE" ]]; then
    echo "Confirmation phrase did not match — nothing was deleted."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running." >&2
    exit 1
fi

if docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
    echo "==> Automatic safety backup before reset"
    scripts/backup_db.sh --auto
else
    echo "WARNING: postgres is not running — cannot take a safety backup."
    printf "Type YES to continue without a backup: "
    read -r NOBACKUP
    if [[ "$NOBACKUP" != "YES" ]]; then
        echo "Aborted — nothing was deleted."
        exit 1
    fi
fi

echo "==> Deleting containers and the database volume"
docker compose down -v
echo "Database volume deleted. Run 'make up' to start fresh."
