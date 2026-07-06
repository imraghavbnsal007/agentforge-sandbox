.PHONY: up down logs seed test

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
