# AgentForge — MVP Design

Date: 2026-07-06 · Status: approved (Phase 1 implemented)

## Goal

A web app where a user submits a software feature request and the system behaves
like an AI engineering assistant: analyze the request, generate a plan, change code
in a sample repo, run tests, and produce a PR-style summary.

## Decisions

- **Agent brain:** real Claude API in Phase 2, with a deterministic mock pipeline
  behind `AGENT_MODE=mock|llm`. Mock is the default and is always used in tests.
- **Queue:** ARQ (async-native, pairs with async SQLAlchemy + FastAPI).
- **No auth in v1** (single local user).
- **Tests:** in-memory SQLite via aiosqlite — fast, no containers required.
- **GitHub integration:** out of scope until Phase 3.

## Architecture

- `backend/` — FastAPI, layered: routes → services → repositories → SQLAlchemy
  models. Pydantic schemas at the boundary. The agent sits behind an `AgentRunner`
  protocol (`StubAgentRunner` now, `LLMAgentRunner` in Phase 2) so the API and
  worker never know which brain runs.
- `frontend/` — Next.js App Router + Tailwind. Server components fetch the API;
  a small client component refreshes on an interval so status transitions are live.
- `sample_repo/` (Phase 2) — toy Python project the agent modifies; each run works
  on a scratch copy.
- Docker Compose: postgres:16, redis:7, backend (uvicorn), worker (arq), frontend.

## Data model

Project 1—N Task 1—N AgentRun 1—N (FileChange, TestResult)

- Task.status: pending → planning → coding → testing → completed | failed
- AgentRun: mode, plan (JSON), summary (markdown), error, timestamps
- FileChange: path, change_type (create/modify/delete), unified diff
- TestResult: suite, passed/failed/errored counts, duration, output

## API

```
GET  /health
GET|POST /api/v1/projects
GET|POST /api/v1/tasks        POST enqueues the ARQ run_agent job
GET  /api/v1/tasks/{id}       includes latest run + file changes + test results
```

## Phases

1. **Done:** skeleton, Compose, models + Alembic, API, worker stub pipeline,
   dashboard, seed data, tests.
2. Sample repo, real agent runners (mock file edits → Claude API), New Task page,
   Task Detail page (plan / diffs / tests / summary panels).
3. GitHub integration, auth, retries, streaming updates.
