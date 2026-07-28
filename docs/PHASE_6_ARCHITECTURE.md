# Phase 6 Architecture — Multi-User GitHub App Access

How AgentForge authenticates people, authorises repositories, and obtains the
credentials it uses to clone, push and open pull requests.

---

## 1. Two modes, one codebase

| | `AUTH_MODE=local` (default) | `AUTH_MODE=github_app` |
|---|---|---|
| Identity | Implicit local user, no sign-in | GitHub OAuth sign-in |
| Repository access | Shared `GITHUB_TOKEN` (PAT) | Per-installation short-lived tokens |
| Registration | Paste a GitHub URL | Pick from installation-granted repositories |
| Allowlist | `GITHUB_ALLOWED_REPOS` | The installation grant *is* the allowlist |
| Commit identity | `AgentForge <agentforge@localhost>` | `GITHUB_APP_COMMIT_NAME/EMAIL` (required) |

**These are separate branches that never converge.** There is no code path
from `github_app` mode to the shared PAT. A failure in the App path aborts the
operation rather than degrading to a broader credential.

Local mode exists so the single-user development workflow keeps working
untouched. Every phase of this work was gated on that.

---

## 2. Request flow

```
Browser
  │  session cookie (HttpOnly, SameSite=Lax) + X-CSRF-Token on writes
  ▼
Next.js  ── forwards cookies on server-side reads ──▶  FastAPI
                                                        │
                          ┌─────────────────────────────┤
                          │  CSRF middleware  (only when a session cookie is present)
                          │  require_user     (router-level, all data routes)
                          ▼
                    get_current_user
                    ├── local mode      → implicit local user
                    └── github_app mode → session cookie → Redis → users row
                          │
                          ▼
                    user-scoped services (ProjectService / TaskService hold the user)
                          │
                          ▼
                    user-scoped repositories (every query filters on user_id)
```

**Identity is established in exactly one place:** `get_current_user` in
`app/api/deps.py`. Nothing downstream re-derives it.

---

## 3. Worker flow

Job payloads carry **only a row id** — `run_agent(task_id)`,
`publish_task(task_id)`, `analyze_project(analysis_id)`. There is deliberately
no `user_id` or `installation_id` in the payload, so there is nothing to
mistakenly trust.

```
arq job (integer id only)
  │
  ▼
reload from database:  task → project → owner → installation → repository grant
  │
  ▼
GitHubCredentialResolver.resolve(project_id, operation, user_id=project.user_id)
  │
  ▼
one credential, for one operation, discarded afterwards
```

---

## 4. Trust boundaries

| Boundary | What crosses it | How it is checked |
|---|---|---|
| Browser → API | Session cookie, CSRF token | Redis session lookup; CSRF only when a cookie is present |
| Browser → API | `installation_id` on the setup callback | **Never trusted.** Verified against the user's own `GET /user/installations` |
| Browser → API | `github_repository_id` on registration | Must be granted to one of the caller's active installations |
| GitHub → API | Webhook payload | HMAC-SHA256 over the raw body, constant-time |
| Queue → Worker | Job payload | **Nothing trusted** — only an integer id; all state re-read from the database |
| API/Worker → GitHub | Installation token | Minted per operation, scoped to one repository |

---

## 5. Where each decision happens

**User identity:** `app/api/deps.py :: get_current_user`.

**Repository ownership:**
- API reads — `ProjectRepository` / `TaskRepository`, which take `user_id` on
  every method. There is no unscoped accessor except one explicitly named for
  the worker.
- Registration — `RepositoryDiscoveryService.find_granted`.
- Credentials — `GitHubCredentialResolver._resolve_installation`, which checks
  ownership, installation liveness, **the owner's link to the installation**,
  and the repository grant.

**Credential minting:** `GitHubAppTokenService.get_installation_token`, cached
in Redis keyed by installation *and* repository scope.

**Credential discard:** credentials are local variables. `GitClient` is
constructed per operation; `GitCredentials.__repr__` hides the token; nothing
is written to PostgreSQL or returned to the frontend.

**Webhook state → future git operations:** webhooks update
`github_installations.suspended_at` / `revoked_at` and add/remove
`github_installation_repositories` rows. The resolver reads exactly those on
its next call, so a revocation blocks the very next operation.

---

## 6. Credential resolution, step by step

`github_app` mode, each step aborting on failure:

1. Load the project fresh from the database
2. Ownership: `project.user_id == user_id`
3. The project must be registered through an installation
4. The installation must exist and be neither suspended nor revoked
5. **The project's owner must still be linked to that installation** — an
   installation can stay active for an organisation while one member's access
   is withdrawn
6. The repository grant row must exist and be neither archived nor disabled
7. Commit identity must be configured
8. Mint a token scoped to that one repository
9. GitHub's reported permissions must cover the operation
   (`contents:read` to clone, `contents:write` to push, `+pull_requests:write` for a PR)

Every access failure returns **one identical message**, so a caller cannot
distinguish "revoked" from "never granted" from "not yours".

---

## 7. Token lifecycle

```
resolve() ──▶ Redis cache hit?
                ├── yes, and > 5 min left  ──▶ reuse
                └── no / near expiry       ──▶ mint from GitHub, cache with
                                               TTL = expiry − 5 min
```

Credentials are **operation-scoped**: publishing resolves separately for clone,
push and PR. That is the refresh mechanism — a long verification run cannot
carry a stale token into the write phase.

On a rejection (git `401`/`403`-shaped, or an API 401/403) the token is
invalidated, access is **fully revalidated**, and a fresh token is minted.
Retry happens at most once, and never blindly: push first asks the remote
whether the branch already carries the commit, and PR creation first looks for
an existing PR on the head branch.

---

## 8. Webhook lifecycle

```
GitHub ──▶ POST /api/v1/github/webhooks
             │
             ├── no secret configured        → 503
             ├── HMAC over RAW body fails    → 401 (body never parsed)
             ├── missing X-GitHub-Delivery   → 400
             │
             ▼
        INSERT delivery row  ── unique violation ──▶ 200 "already processed"
             │
             ▼
        handler (idempotent)  → 200
```

Deduplication is **insert-first**: the unique constraint on `delivery_id`, not
a prior `SELECT`, is what makes concurrent deliveries safe. That same
constraint is the replay defence — a replayed capture carries a still-valid
signature but the same delivery id.

---

## 9. Known limitations

- **Organisation membership is not continuously verified.** A user linked to an
  org installation stays linked until a webhook or a manual re-link changes it.
  Removing the `UserGitHubInstallation` row revokes access immediately, but
  AgentForge does not poll GitHub for membership changes.
- **The repository cache can lag.** It refuses on stale data (fail-closed) but
  cannot grant on it — the token exchange is authoritative.
- **No workspace/team model.** Ownership is a single `user_id`; teams are
  deliberately deferred.
- **Webhook delivery is best-effort.** If deliveries are missed, state is
  corrected on the next manual refresh or the next failed operation.
- **`GITHUB_ALLOWED_REPOS` has no effect in `github_app` mode.** A single global
  list is meaningless across users; the installation grant replaces it.
