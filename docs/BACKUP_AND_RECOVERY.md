# Backup and Recovery

## 1. Backup

```bash
scripts/backup_db.sh          # writes backups/agentforge-YYYYMMDD-HHMMSS.sql
make list-backups
```

The script validates the dump, never overwrites, and honours
`COMPOSE_PROJECT_NAME` so an isolated stack backs up its own database.
`/health` reports backup freshness; `backups/` is mounted **read-only** into
the containers, so nothing running can delete a backup.

**Take a backup before every migration.** Always.

## 2. Restore

```bash
make restore FILE=backups/agentforge-20260728-000759.sql
```

The script takes an automatic pre-restore safety backup, stops the backend and
worker, drops and recreates the `public` schema, loads the dump, runs
`alembic upgrade head`, then restarts. **It never deletes a Docker volume.**

## 3. Migration rehearsal — required for 0011

Migration 0011 is the only destructive migration in Phase 6: it drops the
global `UNIQUE(projects.name)`. Rehearse it in the isolated `agentforge_bktest`
Compose project, which has its **own** `agentforge_bktest_pgdata` volume.

```bash
# 1. backup the real database
scripts/backup_db.sh

# 2. bring up the ISOLATED stack (separate project name = separate volume)
docker compose -p agentforge_bktest up -d postgres

# 3. restore the backup into it
docker compose -p agentforge_bktest exec -T postgres \
  psql -U agentforge -d agentforge -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose -p agentforge_bktest exec -T postgres \
  psql -U agentforge -d agentforge -q < backups/<backup>.sql

# 4. record pre-migration counts, then migrate
docker compose -p agentforge_bktest run --rm --no-deps backend alembic upgrade head

# 5. verify, then tear the isolated stack down
docker compose -p agentforge_bktest down
```

Verify all of:

- row counts unchanged for projects, tasks, agent_runs, project_analyses, llm_runs, file_changes
- every project assigned to the default local user (`github_user_id = 0`)
- zero orphaned tasks, runs, file changes or analyses
- two users may share a project name; one user may not duplicate it
- `github_installation_id` / `github_repository_id` remain nullable and NULL for local projects
- a second run from the same backup produces an identical result

**Never run against the real environment:** `docker compose down -v`,
`make reset-db`, `docker volume rm`, or any destructive migration verification.

## 4. Rollback

| Rev | Downgrade |
|---|---|
| 0013 | Clean. Losing the ledger only means a seen delivery could be reprocessed — handlers are idempotent. |
| 0012 | Clean. Rebuild the cache with **Refresh repositories**. |
| **0011** | **Refuses** if two users share a project name — correctly, since restoring the global constraint would mean deleting someone's project. Resolve duplicates first. |
| 0010, 0009 | Clean (drop additive tables). |

## 5. Failed publish recovery

A publish that cannot complete **never loses work**. The task returns to
`ready_for_review` with its diffs and history intact, and the run records why.

| Cause | Fix |
|---|---|
| Access revoked/suspended | Reinstall or unsuspend, then approve again |
| Repository removed from the installation | Re-grant it, click Refresh repositories, approve again |
| Owner unlinked from the installation | Re-link by reinstalling |
| Token minting failed | Check `GITHUB_APP_ID` and the private key mount; approve again |
| Tests fail on a fresh clone | The base branch moved — retry the task to regenerate |

Retries are safe: push checks whether the branch already carries the commit,
and PR creation checks for an existing PR, so neither is duplicated.

## 6. Revoked installation

History is always preserved — the installation row is retained so past tasks
stay attributable. Only future access is blocked. Reinstalling creates a **new**
installation id, so affected projects must be re-registered.

## 7. Redis loss

Redis holds no durable data. Losing it logs everyone out, clears cached
installation tokens (re-minted on demand) and drops rate-limit counters.
No project, task, run or analysis is affected.
