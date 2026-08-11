# AgentForge

**A human-in-the-loop AI software engineering platform.** It analyses a
repository, plans and implements a change, runs the project's tests, shows you
a reviewable diff, and creates a GitHub pull request **only after you approve
it**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/imraghavbnsal007/agentforge-sandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/imraghavbnsal007/agentforge-sandbox/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Next.js](https://img.shields.io/badge/next.js-15-black)

---

## The problem

Coding agents are good at writing code and bad at being trusted with it. Most
either run entirely on your machine with no audit trail, or take autonomous
action on real repositories where a plausible-looking mistake becomes a commit
before anyone reads it.

AgentForge takes the opposite position: **the agent never touches your
repository until a human has read the diff.** Everything up to that point —
cloning, planning, editing, testing — happens in a disposable workspace. The
approval step is the only path to GitHub, and it is a button a person presses.

Most of the engineering here is therefore not the model. It is the guardrails:
scoped credentials, state machines that cannot contradict themselves, crash
recovery, duplicate-execution locks, and honest reporting when something fails.

## What it does

| | |
|---|---|
| **Analyse** | Clones a repository and detects languages, frameworks, package manager, build/test commands, entry points, API routes and important files. Optionally adds an AI pass for architecture notes, risk areas and grounded improvement suggestions. |
| **Plan** | Turns a plain-English request into a numbered implementation plan. |
| **Implement** | Edits the workspace through a tool-use loop — list, read, write, delete files or whole globs — with every call visible in the execution log. |
| **Test** | Runs the repository's *own* detected test command. If none exists, it says so rather than inventing a pass. |
| **Review** | Per-file unified diffs, test output, execution log, token usage and cost. |
| **Publish** | On approval only: fresh clone, re-apply diffs, re-run tests as a final gate, branch, commit, push, open the PR. |

Also: live execution streaming, task cancellation and retry, multi-user GitHub
sign-in, per-user repository isolation, usage and cost reporting, and crash
recovery for interrupted runs.

## Human approval and safety model

```
pending → planning → coding → testing → READY FOR REVIEW
                                              │
                        [Approve & Create PR] │ [Reject]
                                              ▼
                     publishing → completed (+ PR link)   /   rejected
```

- **Nothing reaches GitHub before approval.** The agent works only in a
  temporary clone; rejecting a task leaves no trace on the remote.
- **Approval re-verifies.** Publishing clones fresh, re-applies the stored
  diffs, and re-runs the tests. If the base branch moved underneath the run,
  it fails loudly rather than forcing a stale change through.
- **Deletions are performed, not patched.** A deletion needs no diff, so it
  cannot fail for reasons unrelated to the deletion itself.
- **Failure is reported honestly.** A run that produced nothing usable is a
  failure; a run that stopped early keeps its work and is labelled
  *incomplete*. Tests that did not run are never reported as tests that passed.
- **Repository scope is enforced per request**, not per session — a task can
  only ever publish to the repository configured on its own project row.

## GitHub integration

AgentForge is a **GitHub App**, not a personal access token pasted into a
form. That distinction is the core of the authorisation design:

- **OAuth is used for identity only.** The user's OAuth token reads their
  profile once, verifies an installation belongs to them, and is then
  discarded. It is never stored, logged, or used against a repository.
- **Repository access uses installation tokens**, minted per operation from
  the App's private key, scoped to exactly the repositories the user granted,
  cached in Redis with an expiry margin so a long clone cannot straddle
  expiry, and never written to disk or a git remote.
- **Webhooks are HMAC-SHA256 verified** with replay protection; a delivery
  that cannot be verified is refused rather than trusted.

Users install the App on their own account or organisation and choose which
repositories it may see. AgentForge cannot enumerate or reach anything else.

## Architecture

```
Next.js 15 (App Router, server components, SSE client)
        │  cookie session + CSRF double-submit
        ▼
FastAPI  ──  api → services → repositories → models
        │
        ├── PostgreSQL 16   tasks, runs, diffs, events, usage
        ├── Redis 7         sessions, execution leases, cancellation, token cache
        └── arq worker      agent runs, publishing, analysis, crash reaper
```

Notable pieces:

- **Task state machine** with explicit legal transitions and terminal-state
  immutability, so status can never contradict itself.
- **Distributed execution leases** (`SET NX EX` plus compare-and-extend) so a
  redelivered job cannot run the same task twice.
- **Heartbeats and a reaper** — a worker beats every 30s; a run silent for
  five minutes is marked abandoned with its work preserved, never discarded.
- **Server-Sent Events** with replay-then-follow and `Last-Event-ID` cursors,
  so a reconnecting browser misses nothing and double-counts nothing.
- **Provider-agnostic LLM layer** — business logic never imports a provider
  SDK.

Deeper design notes live in [`docs/`](docs/):
[architecture](docs/PHASE_6_ARCHITECTURE.md) ·
[task lifecycle](docs/TASK_LIFECYCLE.md) ·
[real-time events](docs/REALTIME_EVENTS.md) ·
[worker recovery](docs/WORKER_RECOVERY.md) ·
[security](docs/SECURITY.md) ·
[error codes](docs/ERROR_CODES.md) ·
[testing](docs/TESTING.md)

## AI providers

| Provider | Status |
|---|---|
| Anthropic (Claude) | Implemented |
| Google (Gemini) | Implemented |
| OpenAI | Registered placeholder — selecting it fails with a clear message |
| OpenRouter | Registered placeholder |
| Ollama | Registered placeholder |

Configuration is environment-only; switching provider or model requires no
code changes. **Execution profiles** map each pipeline phase to a
provider/model — *Cheap*, *Balanced*, *Premium*, or a custom pairing — and the
New Task page shows estimated cost before you run anything.

Every call is recorded with tokens, latency, cost and outcome. Where a price
is unknown the cost is reported as unknown rather than zero.

## Screenshots

> Placeholder — capture and drop into `docs/images/`. See
> [`docs/LINKEDIN_SHOWCASE.md`](docs/LINKEDIN_SHOWCASE.md) for the shot list.

| View | File |
|---|---|
| Dashboard | `docs/images/dashboard.png` |
| Repository picker | `docs/images/repositories.png` |
| Repository analysis | `docs/images/analysis.png` |
| Live execution | `docs/images/execution.png` |
| Diff review | `docs/images/diff.png` |
| Generated pull request | `docs/images/pull-request.png` |
| Usage and cost | `docs/images/usage.png` |

## Demo

A recorded walkthrough is the intended way to see this working end to end —
the full flow touches a real GitHub repository, which a public deployment
should not do. The recording sequence and a safe deployment option are
documented in [`docs/LINKEDIN_SHOWCASE.md`](docs/LINKEDIN_SHOWCASE.md) and
[`docs/DEPLOYMENT_RECOMMENDATION.md`](docs/DEPLOYMENT_RECOMMENDATION.md).

## Local setup

**Requirements:** Docker and Docker Compose. Nothing else.

```bash
git clone https://github.com/imraghavbnsal007/agentforge-sandbox.git
cd agentforge-sandbox
cp .env.example .env
make up
```

Open <http://localhost:3000>. Out of the box this runs in **mock mode** — a
deterministic agent that makes a real edit and runs real tests, with no API
keys and no external calls. The whole pipeline works; only the model is
stubbed.

### Enabling a real model

```bash
# .env
AGENT_MODE=llm
ANTHROPIC_API_KEY=sk-ant-...        # or GOOGLE_API_KEY=...
```

```bash
docker compose up -d --force-recreate backend worker
```

### Enabling GitHub pull requests

Two modes:

- **`AUTH_MODE=local`** — single user, no sign-in, a fine-grained personal
  access token in `GITHUB_TOKEN`. Simplest for solo use.
- **`AUTH_MODE=github_app`** — multi-user with GitHub sign-in and
  per-installation scoped access. See
  [`docs/GITHUB_APP_SETUP.md`](docs/GITHUB_APP_SETUP.md), or run
  `scripts/setup_github_app.sh` and then `scripts/enable_github_app.sh`, which
  validates every prerequisite before switching so you cannot lock yourself
  out.

## Testing

```bash
make test                              # backend suite in the container
cd frontend && npx vitest run          # frontend component tests
make typecheck                         # tsc --noEmit
```

Roughly 920 backend and 76 frontend tests, at about a 1:1 test-to-source
line ratio. The badge above reports the live result — an exact count here would
drift the moment a test is added. See [`docs/TESTING.md`](docs/TESTING.md).

## Deployment limitations

**This repository is configured for local development, not production.** Read
[`docs/DEPLOYMENT_RECOMMENDATION.md`](docs/DEPLOYMENT_RECOMMENDATION.md)
before deploying anything.

In particular, the shipped `docker-compose.yml`:

- runs the API with `uvicorn --reload` and the frontend as a dev server;
- uses a default Postgres password (`agentforge`);
- serves plain HTTP, so `COOKIE_SECURE=false`;
- has no TLS termination, backups schedule, resource limits or restart
  policies.

`SHOWCASE_MODE=true` exists for public demonstration: it forces the mock
agent and refuses publishing, repository registration, analysis and
configuration changes, so a visitor cannot reach a real repository or spend
your API budget.

## ⚠️ Security notice

- **Never commit `.env`, `*.pem`, or any API key.** All are gitignored; this
  repository's history has been verified clean of them.
- A GitHub App private key mints tokens for **every repository the App is
  installed on**. Treat it like a root credential and mount it as a secret.
- `AUTH_MODE=local` performs **no authentication whatsoever** — every request
  is the same implicit user. It is safe only on a machine you control, never
  on a public address.
- The agent executes the repository's own test command inside the worker
  container. Only point it at repositories you trust.

## Roadmap

- [ ] Multi-step tasks that span several files with intermediate review
- [ ] Inline diff comments feeding back into a revision loop
- [ ] Implement the registered OpenAI / OpenRouter / Ollama providers
- [ ] Scheduled repository health reports
- [ ] Production deployment profile with TLS and managed Postgres

## Technology

**Backend** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic
· arq · pytest
**Frontend** TypeScript · Next.js 15 · React 19 · Tailwind CSS 4 ·
framer-motion · Vitest · Testing Library
**Infrastructure** PostgreSQL 16 · Redis 7 · Docker Compose
**Integrations** GitHub Apps · GitHub REST · Anthropic · Google Gemini

## Repository layout

```
backend/     FastAPI app: api → services → repositories → models
  app/agent/     runner interface, mock runner, LLM runner, workspace, executors
  app/llm/       provider-agnostic gateway, profiles, cost tracking
  app/services/  runs, publishing, GitHub App auth, discovery, recovery
  app/worker/    arq worker settings and job queue
frontend/    Next.js dashboard, task detail, projects, usage
sample_repo/ Small Python project the mock pipeline operates on
docs/        Architecture, security, operations and showcase documentation
scripts/     Setup, backup, restore and GitHub App activation helpers
```

## License

[MIT](LICENSE) © Raghav Bansal
