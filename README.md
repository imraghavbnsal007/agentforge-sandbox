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
shows the request, plan, execution log, per-file diffs, test output, the final
PR-style summary, a Retry Task button, and a collapsible "View Raw Logs"
section with the full history of every run (mode, status, error, log).

## Agent modes

The dashboard header shows which mode the server is running; every task row
and task detail page shows which mode produced its latest run.

### Mock mode (default — no API key needed)

```bash
# .env
AGENT_MODE=mock
```

The deterministic `MockRunner` makes a real edit (adds `multiply()` + tests to
the workspace copy) and runs real pytest — the full pipeline without API calls.
Use this for development and demos.

### LLM mode (real Claude agent)

```bash
# .env
AGENT_MODE=llm
ANTHROPIC_API_KEY=sk-ant-...          # required
ANTHROPIC_MODEL=claude-opus-4-8       # optional, this is the default
```

Then restart the backend and worker so they pick up the new env:

```bash
docker compose up -d --force-recreate backend worker
```

`ClaudeRunner` asks Claude for a plan, lets it edit the workspace through a
tool-use loop (`list_files` / `read_file` / `write_file` / `delete_file` —
every call appears in the execution log), runs pytest on the result, and asks
Claude for the PR summary. If the API call fails (bad key, rate limit, network),
the task fails with a readable error shown at the top of the task detail page,
and Retry Task re-enqueues it.

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
