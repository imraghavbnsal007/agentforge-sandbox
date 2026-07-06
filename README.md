# AgentForge

An MVP web app where you submit a software feature request and the system behaves
like an AI engineering assistant: it plans the work, changes code in a sample repo,
runs tests, and produces a PR-style summary.

**Phase 1 status:** project skeleton, Docker Compose stack, backend API + models,
ARQ worker with a deterministic stub agent, and a dashboard listing tasks.
The real agent pipeline (Claude API, sample repo edits, Task Detail UI) is Phase 2.

## Stack

- **Frontend** — Next.js 15 (App Router, Tailwind) on :3000
- **Backend** — FastAPI + SQLAlchemy 2 (async) + Alembic on :8000
- **Database** — PostgreSQL 16
- **Queue** — Redis 7 + ARQ worker
- **Agent** — `AGENT_MODE=mock` (stub runner) today; `llm` arrives in Phase 2

## Quick start

```bash
cp .env.example .env
make up          # docker compose up --build
make seed        # in a second terminal: seed a project + demo tasks
```

Then open:

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs

Create a task and watch the worker drive it through
`pending → planning → coding → testing → completed` on the dashboard:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"project_id": 1, "title": "Add subtract function", "request": "Add subtract(a, b) to the calculator."}'
```

## Tests

```bash
make test        # runs pytest in the backend container (SQLite in-memory, no DB needed)
```

Or locally without Docker:

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest
```

## Layout

```
backend/    FastAPI app: api → services → repositories → models
  app/agent/    AgentRunner interface + stub runner (Claude runner in Phase 2)
  app/worker/   ARQ worker settings + job queue abstraction
frontend/   Next.js dashboard
docs/       Design docs
```
