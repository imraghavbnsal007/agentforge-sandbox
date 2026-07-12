.PHONY: up down restart status logs shell seed test typecheck frontend-reset backup list-backups restore reset-db

# Start all services
up:
	docker compose up --build

# Stop services (KEEP database)
down:
	docker compose down

# Rebuild and restart everything
restart:
	docker compose down
	docker compose up -d --build

# Show running containers
status:
	docker compose ps

# View backend/worker logs
logs:
	docker compose logs -f backend worker

# Open a shell inside the backend container
shell:
	docker compose exec backend sh

# Seed the database
seed:
	docker compose exec backend python -m app.seed

# Run backend tests
test:
	docker compose run --rm --no-deps backend pytest

# Type-check the frontend
typecheck:
	cd frontend && npx tsc --noEmit

# Rebuild frontend with fresh node_modules and .next volumes
frontend-reset:
	docker compose up -d --build --force-recreate --renew-anon-volumes frontend

# Backup PostgreSQL database (validated, atomic, never overwrites)
backup:
	scripts/backup_db.sh

# List available backups
list-backups:
	@ls -lht backups/*.sql 2>/dev/null || echo "No backups yet — run 'make backup'."

# Restore PostgreSQL database (takes a safety backup first, runs migrations)
restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/your-backup.sql" && exit 1)
	scripts/restore_db.sh "$(FILE)"

# PERMANENTLY delete the database volume. Requires typing a confirmation
# phrase; takes an automatic safety backup first. The script is the only
# place in the repo allowed to delete Docker volumes.
reset-db:
	scripts/reset_db.sh