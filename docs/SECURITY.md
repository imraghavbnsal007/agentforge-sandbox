# Security

## 1. Trust boundaries

| Boundary | Crosses it | Enforcement |
|---|---|---|
| Browser → API | Session cookie, CSRF token | Redis lookup; CSRF checked only when a session cookie is present |
| Browser → API | `installation_id` at setup | **Never trusted** — verified against the user's own `GET /user/installations` |
| Browser → API | `github_repository_id` at registration | Must be granted to one of the caller's active installations |
| GitHub → API | Webhook body | HMAC-SHA256 over raw bytes, constant-time |
| Queue → Worker | Job payload | **Nothing trusted** — an integer id only; all state re-read from the database |
| API/Worker → GitHub | Installation token | Minted per operation, scoped to one repository |

---

## 2. Threat model

| Threat | Mitigation | Tested |
|---|---|---|
| User A reads B's project/task/run | Every query scoped by `user_id`; **404, never 403** | ✅ |
| Forged `installation_id` | Verified against the user's own installation list | ✅ |
| Forged webhook | HMAC over raw body, constant-time; missing/invalid → 401 | ✅ |
| Replayed webhook | Unique `delivery_id`; a replay carries a *valid* signature but a seen id | ✅ |
| Revoked installation mid-flight | Re-checked before clone, push and PR | ✅ |
| Member loses org access but installation stays active | Owner↔installation link checked on every credential resolution | ✅ |
| Token expiry during a long task | Credentials resolved per operation; re-minted inside a 5-minute margin | ✅ |
| Token rejected by GitHub | Invalidated, access revalidated, one non-blind retry | ✅ |
| Leaked credentials in logs | Scrubbing in git output, provider errors and audit fields; `__repr__` hides tokens | ✅ |
| Token in git remote/config | Per-command `extraheader`; never written to disk | ✅ |
| SSRF via repository URL | `https://github.com/...` only; in App mode no URL is accepted at all | ✅ |
| Shell/argument injection via task title | Branch names reduced to `[a-z0-9-]`, length-bounded | ✅ |
| Path traversal by the agent | Workspace resolves and rejects paths outside its root | ✅ |
| CSRF | HttpOnly + `SameSite=Lax` cookies, double-submit token | ✅ |
| OAuth code interception | Single-use `state` in Redis, 10-minute TTL, atomic `GETDEL` | ✅ |
| Open redirect after sign-in | Only single-slash-prefixed paths accepted | ✅ |
| Brute force on auth | Fixed-window rate limits on login and callback | ✅ |
| Webhook flooding | Rate limit applied **only to signature failures**, so real deliveries are never throttled | ✅ |

---

## 3. Token lifecycle

**User OAuth token** — used once during the callback to read the profile and,
when an installation is being linked, to verify ownership. Then dropped. It is
**never** written to Redis, PostgreSQL or a session, and never used for Git
operations.

**Installation token** — minted on demand, scoped to a single repository,
valid one hour. Cached in Redis with `TTL = expiry − 5 min`; the read path
independently re-checks expiry. Never in PostgreSQL, never sent to the
frontend, never logged.

**App private key** — read from a file path only, cached by mtime, never
logged and never included in an error message. Failures name the *path* and
the *reason*.

---

## 4. Multi-user isolation

- `ProjectRepository` / `TaskRepository` take `user_id` on **every** method.
  There is no unscoped accessor except one explicitly named for the worker.
- `ProjectService` / `TaskService` hold the user, so no method can run unscoped.
- Tasks inherit ownership through their project.
- Cross-user access returns **404**, and refusal messages are structurally
  identical to the genuine not-found case.

---

## 5. Webhook security

1. No secret configured → **503**
2. Missing or invalid signature → **401**, body never parsed
3. Missing delivery id → **400**
4. Insert-first dedup; duplicate → **200**, not reprocessed
5. Unknown event → **200**, recorded as ignored, no state change

The signature is computed over the **raw** body: re-serialising parsed JSON
would change whitespace and key order, producing a different digest.

---

## 6. Reporting

Report suspected vulnerabilities privately to the repository owner. Do not open
a public issue.

---

## 7. Known limitations

- Organisation membership is not continuously polled; access is corrected by
  webhook, by refresh, or by removing the user↔installation link.
- The repository cache can lag. It is fail-closed: it can refuse but never
  grant — the token exchange is authoritative.
- No workspace/team model; ownership is a single `user_id`.
- Webhook delivery is best-effort. Missed deliveries are corrected on the next
  refresh or the next failed operation.
- Audit events go to a logger (`agentforge.audit`), not a queryable table.
  Route them somewhere durable in production.
