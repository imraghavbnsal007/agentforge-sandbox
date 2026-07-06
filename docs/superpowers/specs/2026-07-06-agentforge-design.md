# AgentForge — MVP Design

Date: 2026-07-06 · Status: approved (Phases 1–2 implemented)

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
2. **Done:** sample repo + Workspace (scratch copy, path-safe file ops, unified
   diffs), PytestExecutor (real subprocess run: stdout/stderr/duration/counts),
   MockRunner (real deterministic edits), ClaudeRunner (plan call + tool-use
   edit loop + summary call on claude-opus-4-8), execution log on AgentRun,
   New Task page, Task Detail page (request / plan / log / diffs / tests /
   summary). Single intelligent agent only — no multi-agent split yet.
3. GitHub integration, auth, retries, streaming updates; split into
   Planner/Coder/Reviewer/QA only once the single agent is reliable.
