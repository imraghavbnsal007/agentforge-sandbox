# Observability

## Layers

| Layer | Purpose | Audience |
|---|---|---|
| `task_events` | Ordered, user-facing execution timeline | Users, via UI and API |
| Run log (`AgentRun.log`) | Full human-readable narrative of one run | Users, on the task page |
| Application logs | Diagnostics, exceptions, warnings | Operators |
| Audit log (`agentforge.audit`) | Security-relevant actions | Operators, security review |

The split is deliberate: **user-facing messages and internal diagnostics are
never the same string.** Users get an error *code* and a sentence; operators get
the exception.

## Safe fields

`user_id`, `project_id`, `task_id`, `run_id`, `stage`, `provider`, `model`,
`duration_ms`, `status`, `error_code`.

## Never logged

Tokens, authorization headers, private keys, OAuth codes, webhook signatures,
model prompts, message history, repository file contents, credential-bearing
command strings.

Enforced in three places: `audit()` drops a `_SENSITIVE_FIELDS` allowlist
violation; `GitClient._scrub` redacts tokens from all git output;
`redact_secrets` catches token *shapes* (`ghs_`, `gho_`, `ghp_`, JWTs) anywhere
they appear.

## Health endpoints

| Endpoint | Checks | Use |
|---|---|---|
| `GET /health` | Nothing external — **never GitHub** | Liveness probe |
| `GET /ready` | PostgreSQL, Redis, configuration | Readiness probe (503 when down) |

`/ready` also reports `auth_mode`, `environment`, `version` and
`migration_revision`. A liveness probe that failed on a Redis blip would
restart a healthy process, which is why `/health` depends on nothing.

## Usage and cost

`llm_runs` records provider, model, tokens in/out, estimated cost, latency and
success per call. `AgentRun.model_calls` / `tool_calls` aggregate per run.

**Unknown pricing is shown as unavailable, never as zero** — a missing price is
not a free call. Cost figures are labelled estimates throughout; there is no
billing.

## Known limitations

- Audit events go to a **logger, not a queryable table**. Route them somewhere
  durable in production.
- There is no distributed trace/correlation id spanning API → queue → worker
  yet; correlation today is by `task_id` and `run_id`.
