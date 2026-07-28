# Release Checklist — Phase 6

## Automated (must all pass before release)

- [ ] Backend suite — `docker compose exec backend python -m pytest -q`
- [ ] Frontend suite — `cd frontend && npm test`
- [ ] Frontend typecheck — `npx tsc --noEmit`
- [ ] Frontend production build — `npx next build`
- [ ] End-to-end mocked flow — `pytest tests/test_integration/test_phase6_end_to_end.py`
- [ ] Multi-user isolation — `pytest tests/test_integration/test_multi_user_isolation.py`
- [ ] Failure/recovery — `pytest tests/test_integration/test_failure_recovery.py`
- [ ] Security tests — `pytest tests/test_integration/test_security_hardening.py`
- [ ] Startup validation — `pytest tests/test_core/`
- [ ] Migration rehearsal in `agentforge_bktest` — see `docs/BACKUP_AND_RECOVERY.md`
- [ ] `GET /ready` returns 200 with all checks passing

## Phase 7 additions

- [ ] State machine — `pytest tests/test_core/test_task_state.py`
- [ ] Events and scrubbing — `pytest tests/test_services/test_task_events.py`
- [ ] Locking — `pytest tests/test_services/test_execution_lock.py`
- [ ] Crash recovery — `pytest tests/test_services/test_run_recovery.py`
- [ ] Task control API — `pytest tests/test_api/test_task_control.py`
- [ ] Migration 0014 rehearsed in `agentforge_bktest`
- [ ] `GET /ready` reports migration revision `0014`
- [ ] SSE verified through the production reverse proxy (buffering **off**)
- [ ] `reap_abandoned_runs` scheduled, or its absence accepted

## Pre-deploy configuration

- [ ] `APP_ENV=production`
- [ ] `COOKIE_SECURE=true`
- [ ] `FRONTEND_URL`, `GITHUB_APP_CALLBACK_URL`, `CORS_ORIGINS` all `https://`
- [ ] `CORS_ORIGINS` lists explicit origins — never `*`
- [ ] `TRUST_PROXY_HEADERS=true` **only** behind a proxy that overwrites `X-Forwarded-For`
- [ ] Private key mounted and readable; **not** in the image or git
- [ ] All `GITHUB_APP_*` values set (startup validation confirms)
- [ ] Fresh database backup taken

## Manual — GitHub workflow (not yet performed)

Use a **throwaway repository**, never one that matters.

- [ ] Sign in with GitHub
- [ ] Install the GitHub App on a throwaway repository
- [ ] Repository appears in discovery
- [ ] Register it
- [ ] Create a task; it runs to `ready_for_review`
- [ ] Approve it
- [ ] Branch is created on the remote
- [ ] Pull request opens **under the App identity**
- [ ] Remove repository access on GitHub → webhook arrives → repository disappears from discovery
- [ ] A further publish attempt is blocked with a clear message, diffs preserved
- [ ] Second user signs in and can see none of the above
- [ ] Live progress updates without a page refresh
- [ ] Cancel stops a running task at its next checkpoint
- [ ] Retry after a failure creates a new run, preserving the old one
- [ ] Killing the worker mid-run leaves the task recoverable, diffs intact
- [ ] Sign out; the session no longer works
- [ ] Restore a backup into the isolated stack and confirm it loads

## Rollback readiness

- [ ] Previous image tag identified
- [ ] Downgrade path confirmed for any migration in the release
- [ ] 0011 downgrade understood: **refuses** while two users share a project name
- [ ] Backup restore rehearsed within the last release cycle
