# Phase 6 — Public GitHub App Authentication and Repository Access

**Status:** awaiting approval. No code written yet.

---

## 1. Inspection findings — what Phase 6 has to change

### 1.1 There is no concept of a user anywhere

Confirmed by inspection:

- No `User` model. `backend/app/models/__init__.py` exports 9 models, none of them a user or session.
- No auth dependency. `backend/app/api/deps.py` provides only `DbSession`, `Queue`, and two service factories.
- No auth middleware in `backend/app/main.py`; CORS is `allow_origins=["http://localhost:3000"]` with **no** `allow_credentials`, so cookie auth cannot work until that changes.
- Every route is unauthenticated and unscoped. `GET /api/v1/projects` returns *all* projects; `GET /api/v1/tasks/{id}` returns any task by ID.

**Consequence:** multi-tenancy is not a filter to be added to a few queries — it is a new axis on every read path. This is the bulk of the work, not the GitHub App itself.

### 1.2 GitHub credentials are a single global PAT, read at 4 call sites

| Location | Use |
|---|---|
| `backend/app/services/project_service.py:54` | `GitClient(token=settings.github_token)` → `ls_remote` validation at registration |
| `backend/app/services/run_service.py:38` | `GitClient(token=settings.github_token)` → clone for the agent workspace |
| `backend/app/services/analysis_service.py:217` | `GitClient(token=settings.github_token)` → clone for analysis |
| `backend/app/services/publisher.py:59-60` | `GitClient` **and** `GitHubAPI` → clone, push, create PR |

Plus `backend/app/api/routes/meta.py:31` exposes `github_token_configured` to the frontend.

**Good news:** `GitClient` is already token-agnostic and injects auth per-command via
`-c http.<url>.extraheader` (`git_client.py:36-39`), so the token never lands in
`.git/config` or a remote URL, and `_scrub()` redacts it from all output. **An
installation token drops straight into this design with no security rework.**
This is the single biggest thing already in our favour.

**Bad news:** `GitClient.clone()` hardcodes the committer identity at
`git_client.py:88-89` (`AgentForge` / `agentforge@localhost`). Acceptance
criterion #9 ("PR created by the GitHub App identity") requires this be
parameterised to the bot identity.

### 1.3 The `Project` model blocks multi-tenancy at the schema level

`backend/app/models/project.py:18`:

```python
name: Mapped[str] = mapped_column(String(200), unique=True)
```

`name` is `"owner/repo"` for registered repos, and it is **globally unique**.
Two different users cannot both register `SnapBin/SnapBin`. `ProjectService.register_project`
compounds this with two global dedup checks (`project_service.py:43-51`):
`get_by_name` and `get_by_github_repo`.

This constraint must be dropped and replaced with a composite unique per owner.
It is the one genuinely delicate migration in Phase 6.

### 1.4 Authorisation is enforced by an env var, not by identity

`backend/app/services/github_config.py` is the entire authorisation model:
`check_repo_allowed()` and `validate_github_project()` compare against
`GITHUB_ALLOWED_REPOS`. In `github_app` mode this must be replaced by
"does this user's live installation grant this repository", while remaining
untouched in `local` mode.

### 1.5 Worker jobs carry only a row ID

`backend/app/worker/settings.py` — all three jobs (`run_agent`, `publish_task`,
`analyze_project`) take a single integer ID and re-load from the DB. No user
context, no re-authorisation.

### 1.6 Frontend has no auth surface at all

- `frontend/src/lib/api.ts` fetches server-side with no cookie forwarding.
- `frontend/src/components/Sidebar.tsx:21-26` — nav is a flat 4-item array, no user menu, no sign-in/out.
- No `middleware.ts`, no `/login` route.
- `RegisterRepoForm.tsx` is a free-text GitHub URL box — exactly the flow the spec says to remove in public mode.

### 1.7 Dependencies missing

`backend/requirements.txt` has no JWT library. GitHub App auth needs RS256
signing → add `pyjwt[crypto]` (pulls in `cryptography`).

Redis **is** already available (used by arq) — server-side sessions and token
caching have infrastructure ready.

### 1.8 Tests will mostly survive

`backend/tests/conftest.py` builds SQLite in-memory schemas via
`Base.metadata.create_all` (not Alembic), and an autouse fixture already
neutralises GitHub settings. So:

- Migrations are exercised **only against Postgres**, never in the test suite. The constraint change therefore needs a dedicated manual verification step.
- 240 existing tests assume unauthenticated routes. Under `AUTH_MODE=local` with a default local user auto-attached, they should keep passing — this is the compatibility guarantee to protect.

---

## 2. Key design decisions (please confirm §2.1 and §2.2)

### 2.1 Worker authorisation: re-derive, don't trust job args

Your spec says worker jobs must *carry* `user_id` / `installation_id`. I'd
recommend a variant, and want your sign-off:

- **Carry** them in the job payload — for logging, tracing and audit.
- **Authorise from the database row at execution time**, not from the payload.

Reason: a job can sit in the Redis queue for minutes. If access is revoked in
that window, a payload-trusted `installation_id` is a stale capability — the
exact thing criterion #11 forbids. Re-deriving `project → installation →
repository` at execution time and re-checking liveness is strictly safer, and
makes the payload advisory rather than authoritative.

Net effect: your requirement ("worker must re-check authorisation and
installation access before cloning or publishing") is satisfied more strongly.

### 2.2 Cookie domain in development

Backend is `localhost:8000`, frontend `localhost:3000`. Cookies ignore port, so
a session cookie set on `localhost` by the backend **is** sent to the frontend
origin — this works in dev without a proxy.

For production I recommend one domain with a path split (`/api` → backend) so
the cookie is same-site and `Secure`. Confirm you're fine with:

- **Dev:** two ports on `localhost`, cookie set by backend.
- **Prod:** single domain behind a reverse proxy.

### 2.3 Derived access state, not a duplicated flag

Rather than an `access_revoked` boolean on `Project` that must be kept in sync,
project operability is **derived**:

> operable = installation exists ∧ not suspended ∧ not deleted ∧ a matching
> `GitHubInstallationRepository` row is present

Single source of truth, cannot drift, and webhook handlers only maintain the
installation/repository tables. A cached `access_state` column can be added
later purely as a query optimisation if list pages get slow.

### 2.4 Sessions in Redis, not signed cookies

Server-side sessions keyed by an opaque random ID in an HTTP-only cookie.
Chosen over signed/stateless cookies because logout and installation-revocation
must be able to **kill a session immediately**, which stateless tokens cannot do
without a blocklist (which is just a session store with extra steps).

---

## 3. Phased implementation plan

Six sub-phases, each independently reviewable and each ending green on tests.

### Phase 6A — User authentication and sessions
Add identity without changing any authorisation yet. `AUTH_MODE=local`
auto-attaches a default local user, so every existing route and all 240 tests
keep working unchanged.

**Backend — new**
- `backend/app/models/user.py` — `User`
- `backend/app/core/security.py` — cookie helpers, CSRF token issue/verify, constant-time compare
- `backend/app/services/session_store.py` — Redis session CRUD, expiry, revoke-all-for-user
- `backend/app/services/oauth_github.py` — authorize URL, `state` issue/verify, code→token exchange, `GET /user`
- `backend/app/api/routes/auth.py` — `GET /api/v1/auth/github/login`, `GET /api/v1/auth/github/callback`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`
- `backend/app/schemas/auth.py`
- `backend/alembic/versions/0009_users_and_auth.py`

**Backend — modified**
- `backend/app/core/enums.py` — `AuthMode` enum
- `backend/app/core/config.py` — `auth_mode` + all `GITHUB_APP_*` settings, private-key loader
- `backend/app/api/deps.py` — `get_current_user`, `require_user`, `CurrentUser`
- `backend/app/main.py` — CORS `allow_credentials=True`, auth router, CSRF middleware
- `backend/app/models/__init__.py`
- `backend/requirements.txt` — `pyjwt[crypto]`

**Frontend — new**
- `frontend/src/app/login/page.tsx` — signed-out landing
- `frontend/src/lib/session.ts` — server-side session read, cookie forwarding
- `frontend/src/components/UserMenu.tsx`
- `frontend/src/middleware.ts` — route protection

**Frontend — modified**
- `frontend/src/lib/api.ts` — forward cookies on server fetches, `credentials: "include"` on client fetches
- `frontend/src/app/layout.tsx`, `frontend/src/components/Sidebar.tsx`

**Tests — new:** `backend/tests/test_api/test_auth.py`, `backend/tests/test_services/test_session_store.py`, `backend/tests/test_services/test_oauth_github.py`

---

### Phase 6B — GitHub App registration, installation callback, token service

**Backend — new**
- `backend/app/models/github_installation.py`
- `backend/app/models/user_github_installation.py`
- `backend/app/models/github_installation_repository.py`
- `backend/app/services/github_app_auth.py` — private-key load, RS256 app JWT
- `backend/app/services/github_app_token_service.py` — `GitHubAppTokenService.get_installation_token(installation_id, repository_ids=None)`, Redis cache keyed by installation + scope, refresh ~5 min before expiry, never logged
- `backend/app/services/github_app_api.py` — list installations, list installation repos, get installation
- `backend/app/api/routes/github_app.py` — `GET /api/v1/github/setup` (installation callback), `GET /api/v1/github/installations`, `POST /api/v1/github/installations/{id}/sync`
- `backend/alembic/versions/0010_github_app_installations.py`

**Tests:** `test_github_app_auth.py`, `test_github_app_token_service.py`, `test_api/test_github_app_setup.py` — including forged installation ID, token-never-logged, cache expiry/refresh.

---

### Phase 6C — Repository discovery and registration

**Backend — new**
- `backend/app/services/repository_discovery.py` — list/sync repos for a user's installations
- `backend/app/api/routes/repositories.py` — `GET /api/v1/repositories`, `POST /api/v1/repositories/refresh`
- `backend/alembic/versions/0011_project_ownership.py` — **the delicate one** (see §4)

**Backend — modified**
- `backend/app/models/project.py` — `user_id`, `github_installation_id`, `github_repository_id`; drop global unique on `name`; add `UniqueConstraint(user_id, name)` and `UniqueConstraint(user_id, github_repository_id)`
- `backend/app/repositories/project_repo.py` — every query scoped by `user_id`
- `backend/app/services/project_service.py` — installation-based registration in `github_app` mode; URL-based retained for `local`
- `backend/app/api/routes/projects.py`, `backend/app/schemas/project.py`

**Frontend — new:** `frontend/src/app/repositories/page.tsx`, `frontend/src/components/RepoPicker.tsx`, `frontend/src/components/InstallAppCard.tsx`
**Frontend — modified:** `RegisterRepoForm.tsx` (local mode only), `projects/page.tsx`, `Sidebar.tsx`

---

### Phase 6D — Git operations and PR workflow on installation tokens

**Backend — new**
- `backend/app/services/github_credentials.py` — `resolve_github_credentials(project)` → token + committer identity, mode-aware. **Never falls back from `github_app` to PAT.**

**Backend — modified**
- `backend/app/services/git_client.py` — parameterised committer identity (bot identity for App mode)
- `backend/app/services/github_api.py` — accept a token provider rather than a fixed token
- `backend/app/services/publisher.py` — resolve credentials per project; re-check access immediately before push/PR; mint the token as late as possible
- `backend/app/services/run_service.py`, `backend/app/services/analysis_service.py` — resolve per project
- `backend/app/services/github_config.py` — mode-aware validation
- `backend/app/worker/settings.py`, `backend/app/worker/queue.py` — carry context, re-authorise at execution

---

### Phase 6E — Webhooks, revocation, security hardening

**Backend — new**
- `backend/app/api/routes/github_webhooks.py` — `POST /api/v1/github/webhooks`, HMAC-SHA256 signature verification
- `backend/app/services/webhook_handler.py` — idempotent handlers for `installation.created/deleted/suspend/unsuspend`, `installation_repositories.added/removed`
- `backend/app/models/webhook_delivery.py` — delivery-ID dedup
- `backend/app/core/ratelimit.py` — Redis fixed-window limiter for auth + callback + webhook routes
- `backend/alembic/versions/0012_webhook_deliveries.py`

**Frontend — modified:** disabled/warning states on project + task pages when access is revoked; "Manage GitHub App Access" link.

---

### Phase 6F — Migration, documentation, end-to-end verification

**New:** `docs/GITHUB_APP_SETUP.md`, `docs/THREAT_MODEL.md`, `docs/DEPLOYMENT.md`
**Modified:** `.env.example`, `docker-compose.yml`, `README.md`, `.gitignore`, `Makefile` (backup-before-migrate target)

---

## 4. Database migrations

| # | File | Contents | Risk |
|---|---|---|---|
| 0009 | `0009_users_and_auth.py` | `users` table + indexes on `github_user_id`, `github_login` | Low — additive |
| 0010 | `0010_github_app_installations.py` | `github_installations`, `user_github_installations`, `github_installation_repositories` | Low — additive |
| 0011 | `0011_project_ownership.py` | **See below** | **HIGH** |
| 0012 | `0012_webhook_deliveries.py` | `webhook_deliveries` + unique on `delivery_id` | Low — additive |

### Migration 0011 in detail — the only risky one

Single atomic transaction:

1. Insert a default local user (`github_login='local'`, sentinel `github_user_id`) **if no users exist**.
2. Add `projects.user_id`, `projects.github_installation_id`, `projects.github_repository_id` — all **nullable**.
3. Backfill `projects.user_id` = default local user for every existing row.
4. Set `projects.user_id` **NOT NULL**.
5. **Drop** the global `UNIQUE` constraint on `projects.name`.
6. Add `UNIQUE (user_id, name)` and a partial `UNIQUE (user_id, github_repository_id) WHERE github_repository_id IS NOT NULL`.

`github_installation_id` and `github_repository_id` stay nullable forever —
that is exactly what keeps local PAT projects legal (criterion #12).

Downgrade path restores the global unique, which **will fail** if two users have
registered the same repo by then. That is correct and intentional: it should
fail loudly rather than silently delete a row.

**Because the test suite uses `create_all` and never runs Alembic, migration 0011
gets a dedicated manual verification against a restored backup copy — never
against your live volume first.**

---

## 5. What you must configure manually on GitHub

Create at **https://github.com/settings/apps/new**.

### Identity
| Field | Value |
|---|---|
| GitHub App name | `AgentForge` (must be globally unique — may need a suffix) |
| Homepage URL | dev `http://localhost:3000` / prod `https://<your-domain>` |
| Description | anything |

### URLs

| Field | Local development | Production |
|---|---|---|
| **Callback URL** (user OAuth) | `http://localhost:8000/api/v1/auth/github/callback` | `https://<domain>/api/v1/auth/github/callback` |
| **Setup URL** (post-install) | `http://localhost:8000/api/v1/github/setup` | `https://<domain>/api/v1/github/setup` |
| **Webhook URL** | `https://<tunnel-host>/api/v1/github/webhooks` | `https://<domain>/api/v1/github/webhooks` |

- Tick **"Request user authorization (OAuth) during installation"**.
- Tick **"Redirect on update"**.
- Webhooks **require a public HTTPS URL** — localhost will not receive deliveries. Any tunnel works; the URL is configuration, not code.

### Permissions (repository) — least privilege
| Permission | Access |
|---|---|
| Metadata | Read-only |
| Contents | Read and write |
| Pull requests | Read and write |

Nothing else. Explicitly **not** administration, org permissions, members, secrets, or workflows.

### Webhook events
Subscribe to exactly: **Installation**, **Installation repositories**.

### Installation scope
"Where can this GitHub App be installed?" → **Any account** (required for public multi-user).

### Secrets to generate and store
1. **Client secret** — generate, copy once.
2. **Webhook secret** — generate a strong random string yourself.
3. **Private key** — "Generate a private key", downloads a `.pem`. **Never committed**; dev = gitignored path, prod = mounted secret file.

Resulting `.env` (values never committed):

```
AUTH_MODE=local
GITHUB_APP_ID=
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=
GITHUB_APP_PRIVATE_KEY_PATH=/run/secrets/agentforge-app.pem
GITHUB_APP_WEBHOOK_SECRET=
GITHUB_APP_NAME=
GITHUB_APP_CALLBACK_URL=
GITHUB_APP_SETUP_URL=
```

---

## 6. Operations that touch the real database or real GitHub

Flagged per your standing constraints. **Nothing here runs without your explicit go-ahead at the time.**

### Real database
| Operation | Phase | Safeguard |
|---|---|---|
| Alembic 0009, 0010, 0012 | 6A/6B/6E | Additive only; `make backup` first |
| **Alembic 0011** | 6C | **Backup, then rehearse on a restored copy in the isolated `agentforge_bktest` project, then apply** |
| Backfill of existing projects to the local user | 6C | Inside 0011's transaction; verified by row counts before/after |

Existing tasks, runs, analyses and `llm_runs` are **never** rewritten or deleted.
No volume is deleted. `reset-db` and `docker compose down -v` are not used.

### Real GitHub
| Operation | When | Note |
|---|---|---|
| Creating the GitHub App | Before 6B | You do this in your account |
| Installing it on a repo | 6B verification | Suggest a throwaway repo, not SnapBin, for the first run |
| `ls_remote` / clone with an installation token | 6D | Read-only |
| **Branch push + PR creation** | 6D/6F E2E | Writes to a real repo — I'll ask first and suggest the sandbox repo |
| Webhook deliveries | 6E | Inbound only; requires your tunnel running |

### Never in the normal test suite
No live GitHub calls. Mocked HTTP + a local bare git repo, matching the existing
Phase 3 test approach.

---

## 7. Threat model (to be written out fully in `docs/THREAT_MODEL.md`)

| Threat | Mitigation |
|---|---|
| User A reads User B's project/task/run/analysis | Every query scoped by `user_id`; **404 not 403** so existence isn't leaked |
| Forged `installation_id` in the setup callback | Never trusted from the request — verified against GitHub's API and matched to the authenticated user's installations |
| Forged webhook | HMAC-SHA256 over the raw body with `GITHUB_APP_WEBHOOK_SECRET`, constant-time compare; missing/invalid signature → 401 |
| Replayed webhook | `webhook_deliveries` unique on `X-GitHub-Delivery`; duplicates acknowledged, not reprocessed |
| Revoked installation mid-flight | Access re-checked in the worker immediately before clone and again before push/PR |
| Token expiry during a long task | Token minted as late as possible, refreshed ~5 min before expiry, never reused across phases |
| Repository removed during execution | Membership re-verified before publish; task changes preserved, clear error, stays `ready_for_review` |
| Leaked logs | `GitClient._scrub` + provider `scrub()` + explicit installation-token redaction; tokens never persisted to Postgres |
| Token in git remote | Already prevented — per-command `extraheader`, never written to `.git/config` |
| SSRF via repository URL | `github.com` only via the existing regex; in App mode no URL is accepted at all — only installation-granted repository IDs |
| CSRF | HTTP-only + `SameSite=Lax` cookies, CSRF token on state-changing requests |
| OAuth code interception | Single-use `state` in Redis with short TTL, verified on callback |
| Org approval pending | Installation recorded as pending; repository operations blocked with an explanatory message |
| Malicious repository content | Existing analysis caps (file size/count, no `.env`/secrets, zip-slip guard) already apply |
| Brute force on auth endpoints | Redis fixed-window rate limit on auth, callback, webhook |

---

## 8. Test plan

Roughly **+90 backend tests** across the six sub-phases, matching the spec's list:
auth (callback, invalid state, expired session, logout), installation (valid,
forged ID, suspend, delete, repos added/removed, duplicate delivery), repository
access (list authorised, cross-user denial, ungranted registration refused,
removed repo disabled, **local mode backward compatible**), tokens (JWT
generation, exchange, Redis caching, expiry refresh, never logged, revoked
failure), git operations (clone, push, PR, access re-check, no token in remote
config), authorisation (IDOR across projects/tasks/runs/analyses, worker
revalidation), webhook security (valid/invalid/missing signature, replay).

Existing 240 tests must stay green throughout — that is the `AUTH_MODE=local`
compatibility contract.

---

## 9. Recommended sequencing

6A → 6B → 6C → 6D → 6E → 6F, one commit per sub-phase.

6A and 6B are additive and low-risk. **6C carries the only dangerous
migration** and deserves the most review attention. 6D is a broad but mechanical
refactor of four credential call sites. 6E is self-contained. 6F is docs plus
live verification.

---

## 10. Open questions for you

1. **Worker authorisation** — approve the §2.1 variant (carry for audit, authorise from DB)?
2. **Production topology** — single domain behind a reverse proxy (§2.2)?
3. **Workspaces** — the spec says "user_id or workspace_id" throughout. I propose **`user_id` now**, with workspaces deferred; a `workspace_id` can be layered on later without redoing scoping. Confirm?
4. **First live install** — use a throwaway repo rather than `SnapBin/SnapBin` for the first real PR test?
5. **Sub-phase review cadence** — commit each of 6A–6F separately for your review, or batch 6A+6B?
