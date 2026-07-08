.PHONY: up down logs seed test typecheck frontend-reset

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f backend worker

seed:
	docker compose exec backend python -m app.seed

# Tests use in-memory SQLite, so no database container is required.
test:
	docker compose run --rm --no-deps backend pytest

# Type-check the frontend without producing any build output (.next untouched).
typecheck:
	cd frontend && npx tsc --noEmit

# Rebuild the frontend with FRESH node_modules and .next volumes.
# Use after changing frontend dependencies or when the dev server serves
# stale chunks that a normal restart doesn't fix.
frontend-reset:
	docker compose up -d --build --force-recreate --renew-anon-volumes frontend
