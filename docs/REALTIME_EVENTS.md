# Real-Time Events

## Why SSE, not WebSockets

The traffic is one-directional, it rides on plain HTTP so the existing session
cookie authenticates it unchanged, and browsers reconnect and resend
`Last-Event-ID` on their own. A WebSocket would have meant a second auth path
and a hand-written reconnect loop for no benefit.

## The stream is not the source of truth

Events are **persisted before they are published**. PostgreSQL holds them;
Redis pub/sub only delivers them. A client that misses live events replays from
`GET /tasks/{id}/events?after_id=N`, so a dropped connection costs nothing.

```
worker ──▶ task_events (PostgreSQL)  ← replay source
              │
              └──▶ Redis channel ──▶ SSE ──▶ browser
```

## Connect flow

1. `GET /api/v1/tasks/{id}/stream` — session-authenticated, user-scoped
2. Everything after the client's cursor is replayed from PostgreSQL
3. The stream switches to live messages
4. Anything with `id <= cursor` is dropped, so the replay/subscribe race cannot
   deliver an event twice
5. Comment heartbeats every 20s keep proxies from closing an idle connection

## Ordering

`sequence_number` is monotonic **per run**, enforced by
`UNIQUE(run_id, sequence_number)`. The row `id` is the replay cursor and the
SSE `id:` field the browser echoes back.

## Event types

`task_queued`, `run_started`, `stage_changed`, `progress`, `tool_started`,
`tool_completed`, `tests_started`, `tests_completed`, `file_changed`,
`cost_updated`, `warning`, `run_failed`, `run_cancelled`, `review_ready`,
`publish_started`, `branch_pushed`, `pr_created`, `publish_failed`,
`heartbeat`.

## What is never streamed

`safe_metadata` is an **allowlist, not a blocklist** — a new field is invisible
until someone deliberately admits it, which is the right default when the
alternative is leaking a token. Forbidden outright: tokens, authorization
headers, private keys, prompts, message history, diffs, file contents,
environment variables, command lines.

Messages are redacted through `redact_secrets` and capped at 1000 characters.
Stack traces never reach an event — they go to the log, and the user sees a
typed error code.

## Client behaviour

`useTaskEvents` loads history first, then streams. After three consecutive SSE
failures it falls back to polling the same endpoint rather than retrying
forever, and surfaces a **Reconnect** control. A finished task does not stream
at all.

## Retention

Events are diagnostics, not history — the run row keeps the durable outcome.
`TaskEventService.prune(keep_days=30)` bounds the table; wire it to a schedule
if volume warrants.
