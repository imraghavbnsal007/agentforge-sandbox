# Worker Reliability and Recovery

## Duplicate execution

Nothing previously stopped the same task being enqueued twice and run by two
workers concurrently, each creating runs and each mutating task status.
Disabling a button is not a guarantee.

Now every job takes a **lease** before doing anything:

```python
lease = await lock.acquire(task_id)
if lease is None:
    return          # another worker has it — standing down is correct
```

`SET NX EX` decides the winner in Redis, not in application code. Execution and
publishing hold separate leases, so they never block each other.

The lease is renewed while the worker works (`compare_and_extend`, so a worker
whose lease already lapsed cannot resurrect it and collide with whoever took
over). A crashed worker's grip therefore expires on its own — no manual
clearing.

Second line of defence: `execute_agent_run` refuses outright if the task is
already in a terminal state, so a redelivered job is harmless even without the
lock.

## Crash recovery

| Worker dies… | Result |
|---|---|
| before cloning | Run reaped as `abandoned`; task `failed`; retryable |
| during generation | Same; partial output preserved |
| during tests | Same |
| after changes generated | **Diffs preserved**; retry regenerates |
| before state commit | The uncommitted step is lost; the run is reaped |
| during push | Flagged for reconciliation — see below |
| after push, before saving | Retry checks the remote before re-pushing |
| after PR, before saving | Retry looks for an existing PR before creating one |

A `running` row whose heartbeat is older than 300s has lost its worker.
`reap_abandoned_runs` marks it `abandoned` with `worker_interrupted`, moves the
task to `failed`, and **preserves everything it produced**.

Run it periodically:

```bash
docker compose exec worker python -c "
import asyncio
from app.worker.settings import reap_abandoned_runs
print(asyncio.run(reap_abandoned_runs({})))"
```

## Non-idempotent operations are never blindly retried

Push and PR creation may have succeeded before the response was lost. So:

- before re-pushing, `remote_branch_sha` asks whether the branch already
  carries our commit;
- before re-creating a PR, `find_pull_request` looks for one on the head
  branch.

Retry happens at most once, and only after that reconciliation.

## Cancellation checkpoints

`RunTracker.checkpoint()` raises `RunCancelled` at:

entering every stage · after plan generation · after change generation ·
before tests · before summarising · before push · before PR creation

Cancellation is recorded in **both** Redis (promptness) and
`AgentRun.cancel_requested_at` (durability), so it survives a Redis restart and
is still honoured at the next checkpoint. A queued task with no running run is
cancelled outright, since no checkpoint would ever be reached.

Cancellation is user-scoped: another user's task is a 404.

## Redis outage

| Lost | Effect |
|---|---|
| Session store | Everyone signed out |
| Installation-token cache | Tokens re-minted on demand |
| Execution leases | Duplicate protection degrades — the terminal-state guard still holds |
| Event channel | Live streaming stops; clients fall back to polling, and history is intact in PostgreSQL |

No durable data is in Redis.
