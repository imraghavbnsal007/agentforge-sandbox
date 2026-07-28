# Phase 7 Architecture — Real-Time Execution

Turns task execution from a black box you poll into an observable, controllable,
recoverable workflow. Phase 6's ownership and credential model is unchanged.

See also: `TASK_LIFECYCLE.md`, `REALTIME_EVENTS.md`, `WORKER_RECOVERY.md`,
`ERROR_CODES.md`, `OBSERVABILITY.md`.

## What was wrong

| Gap | Before | Now |
|---|---|---|
| Status transitions | Assigned in 11 places, nothing validated | One state machine; illegal moves raise |
| Run granularity | 3 statuses, no stage | 14 stages with weighted progress |
| Frontend updates | `router.refresh()` every 3s | SSE with replay; polling only as fallback |
| Worker crash | Task stuck in `coding` forever | Heartbeat → reaped as `abandoned`, retryable |
| Duplicate execution | Nothing prevented it | Redis lease + terminal-state guard |
| Cancellation | **Did not exist** | Checkpointed, durable, user-scoped |
| Failure reasons | Raw exception text | Typed codes with recommended actions |

## Components

```
API ── TaskService ──▶ enqueue(task_id only)
                            │
                            ▼
Worker ── acquire lease ──▶ RunService ──▶ RunTracker
   │        (Redis)              │            ├── stage + progress
   │                             │            ├── heartbeat  (proves liveness)
   │                             │            ├── checkpoint (RunCancelled)
   │                             │            └── emit ──▶ TaskEventService
   │                                                          │
   └── release lease                            persist ──────┤
                                                              ▼
                                              PostgreSQL (truth) ──▶ Redis ──▶ SSE
```

`RunTracker` owns stage, progress, heartbeat, cancellation and event emission
together, deliberately: they all have to happen at the same moments, and
splitting them is how the old code ended up with transitions in eleven places
and no heartbeat at all.

## Trust and safety

Job payloads carry **only a row id**. Everything else — owner, installation,
repository grant — is re-read from the database, so a redelivered or duplicated
job cannot smuggle in stale state. This is the Phase 6 rule extended: payload
values are never current authorisation.

Cancellation is user-scoped. Event streams are user-scoped. Another user's task
is a 404 on every control.

## Migration 0014

Additive only: eight columns on `agent_runs` (all defaulted or nullable) plus
`task_events`. No existing column altered, no row rewritten. Historical runs get
`stage='queued'`, `progress=0` — accurate, since they predate stage tracking and
their real position is already in `status` and `log`.

## Known limitations

- **The reaper is not scheduled.** `reap_abandoned_runs` is registered as a
  worker function but has no cron trigger; run it periodically or wire a
  schedule.
- **Sequence numbers use max+1.** Safe because one worker holds the lease, but
  not safe under concurrent writers to the same run.
- **No correlation id** spanning API → queue → worker; correlation is by
  `task_id`/`run_id`.
- **Publish-stage events are partial.** Push and PR emit through the run log and
  status, but `GitHubPublisher` does not yet take a `RunTracker`, so publishing
  has fewer live events than execution.
- **Cost per run is aggregated from `llm_runs` on read**, not denormalised onto
  the run row.
