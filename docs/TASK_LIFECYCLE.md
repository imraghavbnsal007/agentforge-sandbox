# Task Lifecycle

Before Phase 7, status was assigned directly in eleven places across three
services with nothing checking the result. Every transition is now explicit and
rejectable — see `app/core/task_state.py`.

## Task states

```
                 ┌──────────────── retry ────────────────┐
                 │                                       │
  pending ─▶ planning ─▶ coding ─▶ testing ─▶ ready_for_review
     │           │          │         │              │
     │           │          │         │              ├─▶ publishing ─▶ completed
     │           │          │         │              │        │
     │           │          │         │              │        ├─▶ publish_failed ─┐
     │           │          │         │              │        └─▶ ready_for_review│
     │           │          │         │              └─▶ rejected ────────────────┤
     └───────────┴──────────┴─────────┴──▶ failed / cancelled ─────────────────────┘
                                              (all retryable → pending)
```

| State | Meaning |
|---|---|
| `pending` | Queued, not yet picked up |
| `planning` / `coding` / `testing` | Executing |
| `ready_for_review` | Changes generated, awaiting approval |
| `publishing` | Pushing and opening a PR |
| `completed` | **Terminal.** Nothing may follow |
| `failed` / `cancelled` / `publish_failed` / `rejected` | Recoverable — retry re-queues |

**`completed` is the only truly terminal state.** Re-running finished work
means creating a new task, so a finished result is never ambiguous.

## Run states and stages

`RunStatus` is the coarse outcome (`running`, `completed`, `failed`,
`cancelled`, `abandoned`). `RunStage` is the fine-grained position:

`queued → preparing → cloning → analysing → planning → generating → testing →
summarising → awaiting_review`, then `pushing → creating_pr → completed` for
publishing.

## Progress

Stage-weighted, never fabricated:

| Stage | % |
|---|---|
| queued | 0 |
| preparing | 5 |
| cloning | 10 |
| analysing | 20 |
| planning | 35 |
| generating | 50 |
| testing | 70 |
| summarising | 85 |
| awaiting_review | 100 |

We cannot know how far through a model call we are, so we do not pretend to.
Progress never moves backwards within a run (`advance_progress` clamps), and
**publishing uses a separate scale** so a push never appears to rewind
completed generation.

## Invariants

- **Terminal runs are immutable.** A retry creates a *new* `AgentRun`; the
  previous one keeps its logs, diffs and test results.
- **Task and run cannot contradict.** `reconcile()` is the single place that
  maps a finished run onto its task.
- **Invalid transitions raise.** `assert_transition` throws
  `InvalidTransitionError` rather than corrupting history silently.
- **A terminal task cannot be executed.** `execute_agent_run` refuses up front,
  which is what makes a redelivered job harmless.

## Retry

Retry is allowed from `failed`, `cancelled`, `publish_failed`, `rejected` and
`ready_for_review`. It refuses while a run is still `running`, and refuses from
`completed`.

Each retry re-resolves GitHub credentials and re-checks ownership and
repository access — nothing is carried over from the previous attempt.
