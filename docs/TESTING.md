# Testing

## Running

```bash
docker compose exec backend python -m pytest -q     # backend
cd frontend && npm test                             # frontend
cd frontend && npx tsc --noEmit                     # typecheck
cd frontend && npx next build                       # production build
```

## Ground rules

**No live GitHub requests in the normal suite.** Every GitHub HTTP call is an
`httpx.MockTransport` or a scripted double. Git is exercised against **real
local bare repositories** under `tmp_path` — real git, fake remote.

**No live task runs.** Agent output is deterministic in tests; the LLM is never
called.

**Isolated state.** The backend suite builds SQLite in-memory schemas via
`Base.metadata.create_all`; Redis is replaced by `InMemoryKVStore`, fresh per
test. Migrations therefore get **no coverage from the suite** — they are
validated separately by rehearsal (see `docs/BACKUP_AND_RECOVERY.md`).

## Layout

| Path | Covers |
|---|---|
| `tests/test_api/` | HTTP boundary: auth, webhooks, repositories, multi-tenancy |
| `tests/test_services/` | Services: credentials, tokens, discovery, publisher, webhooks |
| `tests/test_core/` | Configuration validation |
| `tests/test_integration/` | End-to-end flow, isolation, failure/recovery, security |
| `tests/test_agent/`, `tests/test_llm/` | Agent pipeline and providers |

## The four integration suites

**`test_phase6_end_to_end.py`** — one test walking steps A→Q: mocked sign-in,
installation link, discovery, registration, task creation, worker credential
resolution, real clone, deterministic change, review, approval, real push to a
bare repo, mocked PR, a signed webhook withdrawing access, and the next attempt
being blocked. It ends by asserting no token appears in Redis, any API
response, git config, the database, or the logs.

**`test_multi_user_isolation.py`** — User A owns a repository and project;
User B can see none of it and reach none of it. Includes worker-level
rejection, so bypassing the API entirely still fails.

**`test_failure_recovery.py`** — Redis down, GitHub unreachable, clone/push/PR
failures, lost responses after a successful operation, duplicate publish,
worker restart, and a webhook arriving mid-task. The invariant asserted
throughout: **generated diffs and task history always survive.**

**`test_security_hardening.py`** — branch-name injection, URL validation,
workspace path traversal, credential hygiene, CSRF, webhook signatures, and
that no PAT fallback exists in `github_app` mode.

## Phase 7 suites

**`test_core/test_task_state.py`** — every legal and illegal transition,
terminal immutability, monotonic progress, and reconciliation.

**`test_services/test_task_events.py`** — allowlist scrubbing, per-run
sequencing, cursor replay, and that a broadcast failure never sinks the run.

**`test_services/test_execution_lock.py`** — mutual exclusion, lease ownership,
renewal after expiry, and stale-run detection.

**`test_services/test_run_recovery.py`** — reaping abandoned runs while
preserving their diffs, and flagging crashed publishes for reconciliation.

**`test_api/test_task_control.py`** — cancel/retry/events/stream at the HTTP
boundary, including cross-user 404s and that no token reaches the wire.

**Frontend `TaskLivePanel.test.tsx`** — replay, live append, deduplication,
connection states, SSE→polling fallback, and the cancel/retry controls. jsdom
has no `EventSource`, so a fake stands in.

## Writing new tests

- Assert the behaviour, not the implementation.
- Any new credential path needs a "no token leaks" assertion.
- Any new user-scoped query needs a cross-user 404 test.
- Any new webhook action must be proven idempotent.
- Never add a test that reaches the network.
