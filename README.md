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

## GitHub PR workflow

Projects with GitHub configuration follow a **review-gated** flow instead of
finishing at `completed`:

```
pending → planning → coding → testing → READY FOR REVIEW
                                             │
                       [Approve & Create PR] │ [Reject]
                                             ▼
                    publishing → completed (+ PR link)   /   rejected
```

The agent works on a shallow clone of your repo. When tests pass, the task
stops at **ready for review** — nothing touches GitHub yet. On the task page
you review the plan, diffs, and test results, then click **Approve & Create
PR**. Only then does AgentForge clone fresh, re-apply the stored diffs
(`git apply` — fails loudly if the base branch moved), re-run pytest as a final
gate, create a branch (`agentforge/task-<id>-<slug>`), commit, push, and open
the PR. **Reject** closes the task with no GitHub activity. If publishing
fails (bad token, moved base branch), the task returns to ready-for-review
with the exact error shown, so you can fix the cause and approve again.

### Setup

1. Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens)
   scoped to the target repo with **Contents: Read and write** and
   **Pull requests: Read and write**.
2. Add to `.env` (never committed; never logged):

   ```
   GITHUB_TOKEN=github_pat_...
   GITHUB_ALLOWED_REPOS=you/your-repo    # optional but recommended allowlist
   ```

3. Restart: `docker compose up -d --force-recreate backend worker`
4. Register a GitHub-configured project:

   ```bash
   curl -X POST http://localhost:8000/api/v1/projects \
     -H 'Content-Type: application/json' \
     -d '{
       "name": "My Repo",
       "repo_url": "https://github.com/you/your-repo.git",
       "default_branch": "main",
       "github_owner": "you",
       "github_repo": "your-repo"
     }'
   ```

5. Create tasks against that project from the New Task page.

Safety: tasks can only publish to the repo configured on their project row;
the optional `GITHUB_ALLOWED_REPOS` allowlist refuses anything else even if a
project is misconfigured; the token is injected via a git header (never stored
in remotes or `.git/config`) and scrubbed from all logs and error messages.
Projects without GitHub fields keep the plain sample-repo flow.

## Repository intelligence

The **Projects** page (http://localhost:3000/projects) registers and analyzes
repositories:

- **Register** — paste a GitHub URL (+ branch, default `main`). Registration is
  lightweight: it validates the URL, checks the allowlist, verifies the repo and
  branch are reachable (`git ls-remote`), and saves. No cloning, no AI calls.
- **Analyze** — on the project page, *Analyze Repository* enqueues a worker job
  that clones the repo and detects languages, frameworks, package manager,
  build/test commands, and important files (deterministic heuristics), then —
  in llm mode — asks Claude for a summary, architecture notes, risk areas,
  per-file purposes, and improvement suggestions. Creating a project's *first
  task* also triggers analysis automatically. Re-analyze any time; analyses are
  kept as history.
- **Create Task from Suggestion** — each suggestion links to a prefilled New
  Task form.
- **Detected test command** — tasks against an analyzed project run its
  detected command (e.g. `npm test`) instead of assuming pytest. If analysis
  found **no test command**, AgentForge does not fake results: the test phase
  is skipped, the log and task page say
  *"No automated test command detected"*, and the task still reaches
  ready-for-review with an explicit unverified warning.

Analysis never reads `.env*`, secret/credential/key files, `node_modules`,
`venv`, `dist`, `build`, or binary files, and caps file sizes and counts.

### Deep intelligence (Phase 4.1)

- **Archives** — `.zip` / `.tar.gz` / `.tgz` files are extracted into a
  temporary analysis workspace (zip-slip-guarded, size-capped) and analyzed
  like committed files. Extracted files are never committed and are deleted
  with the workspace.
- **Semantic understanding** — project type, entry points, API routes
  (FastAPI/Django/Spring), React pages/components, and a logical repository
  map (for SQL: Database → Tables / Views / Procedures / Triggers).
- **SQL schema analysis** — tables, columns, primary/foreign keys, CHECK
  constraints, uniques, indexes, views, procedures, triggers, plus a schema
  summary and grounded findings (tables without PKs, `*id` columns without FK
  constraints, views dropped but never created). The AI pass compares the
  schema against README business rules and flags unenforced ones.
- **Health score** — 0–100 overall with deterministic sub-scores for
  structure, documentation, testing, maintainability, and security, each with
  the reason it was assigned.
- **Grounded suggestions** — every suggestion carries confidence, effort,
  reasoning, and must cite real files; ungrounded LLM suggestions are dropped.
  Anything undeterminable is reported as
  "Unable to determine from repository." rather than guessed.

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
