# AgentForge

An MVP web app where you submit a software feature request and the system behaves
like an AI engineering assistant: it plans the work, changes code in a sample repo,
runs tests, and produces a PR-style summary.

**Phase 2 status:** the pipeline is real. Each task copies `sample_repo/` into a
scratch workspace, generates a plan, edits files, computes unified diffs, runs
pytest in the workspace, and writes a PR-style summary. Two agent brains sit
behind the same `AgentRunner` interface:

- `AGENT_MODE=mock` (default) — deterministic agent, no API calls; makes a real
  edit and runs real tests.
- `AGENT_MODE=llm` — **ClaudeRunner**: Claude plans the change, then edits the
  workspace through a tool-use loop (`list_files` / `read_file` / `write_file` /
  `delete_file`). Requires `ANTHROPIC_API_KEY` in `.env`.

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
- New Task: http://localhost:3000/tasks/new
- API docs: http://localhost:8000/docs

Submit a task from the New Task page and watch it move through
`pending → planning → coding → testing → completed`. The Task Detail page
shows the request, plan, execution log, per-file diffs, test output, and the
final PR-style summary.

To use the real Claude agent, set in `.env` and restart:

```
AGENT_MODE=llm
ANTHROPIC_API_KEY=sk-ant-...
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
  app/agent/    AgentRunner interface, MockRunner, ClaudeRunner,
                Workspace (scratch copy + diffs), PytestExecutor
  app/worker/   ARQ worker settings + job queue abstraction
frontend/   Next.js dashboard, New Task, and Task Detail pages
sample_repo/  Tiny Python project the agent operates on (never edited in place)
docs/       Design docs
```
