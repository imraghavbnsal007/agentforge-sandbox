# Deployment

## 1. Topology

Frontend and backend stay separate internally but are exposed through **one
origin** in production:

```
https://agentforge.example.com/          → Next.js
https://agentforge.example.com/api/...   → FastAPI
```

One origin keeps the session cookie same-site and lets `Secure` cookies work
without cross-origin complications. Local development uses two ports
(`:3000` and `:3000`→`:8000`), which works because cookies ignore port.

**HTTPS is required in production.** Startup validation refuses to boot with
`APP_ENV=production` unless cookies are `Secure` and every URL is `https://`.

---

## 2. Environment variables

### Always
| Variable | Notes |
|---|---|
| `DATABASE_URL` | PostgreSQL, `postgresql+asyncpg://…` |
| `REDIS_URL` | Sessions, OAuth state, installation-token cache |
| `AGENT_MODE` | `mock` or `llm` |
| `AUTH_MODE` | `local` (default) or `github_app` |
| `APP_ENV` | `development` or `production` |

### Local mode only
| Variable | Notes |
|---|---|
| `GITHUB_TOKEN` | PAT with Contents + Pull requests read/write |
| `GITHUB_ALLOWED_REPOS` | Optional allowlist. **No effect in `github_app` mode.** |

### `github_app` mode — all required
| Variable | Purpose |
|---|---|
| `GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET` | GitHub sign-in |
| `GITHUB_APP_ID` | JWT issuer |
| `GITHUB_APP_PRIVATE_KEY_PATH` | Signing key for installation tokens |
| `GITHUB_APP_WEBHOOK_SECRET` | Webhook signature verification |
| `GITHUB_APP_COMMIT_NAME` / `GITHUB_APP_COMMIT_EMAIL` | Commit attribution |
| `GITHUB_APP_NAME` | URL slug for the install link (warning if unset) |

### Cookies, CORS, proxy
| Variable | Development | Production |
|---|---|---|
| `COOKIE_SECURE` | `false` | **`true`** |
| `FRONTEND_URL` | `http://localhost:3000` | `https://…` |
| `GITHUB_APP_CALLBACK_URL` | `http://localhost:8000/…` | `https://…` |
| `CORS_ORIGINS` | `http://localhost:3000` | `https://…` — **never `*`** |
| `TRUST_PROXY_HEADERS` | `false` | `true` *only* behind a proxy that overwrites `X-Forwarded-For` |

`CORS_ORIGINS=*` fails at startup: a wildcard cannot be combined with
credentialed requests.

---

## 3. Private key mounting

Never commit the key (`*.pem` and `secrets/*` are gitignored).

**Development** — drop the `.pem` into `secrets/`, mounted read-only:

```yaml
volumes:
  - ./secrets:/run/secrets:ro
```

**Production** — mount a real secret at the same path. The key is read once,
cached by mtime (so rotation is picked up), and **never logged**. If the mount
briefly disappears, the cached key keeps being served rather than failing every
operation — GitHub, not the filesystem, is the authority on validity.

---

## 4. Reverse proxy expectations

- Terminate TLS; forward `/api/*` to the backend, everything else to the frontend
- Preserve the `Cookie` and `X-CSRF-Token` headers
- Overwrite (do not append) `X-Forwarded-For`, then set `TRUST_PROXY_HEADERS=true`
- Do **not** buffer or rewrite the webhook request body — the HMAC is computed
  over the exact bytes GitHub sent

---

## 5. Migration procedure

Migrations run automatically on backend start (`alembic upgrade head`).
For an existing deployment, do it deliberately instead:

```bash
scripts/backup_db.sh                       # 1. always first
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

**Migration 0011 (project ownership) is the only destructive one.** It drops the
global `UNIQUE(projects.name)`. Rehearse it before applying — see
`docs/BACKUP_AND_RECOVERY.md`.

Phase 6 migrations:

| Rev | Contents | Risk |
|---|---|---|
| 0009 | `users` | Additive |
| 0010 | installations + user links | Additive |
| **0011** | **project ownership; drops global unique** | **Destructive** |
| 0012 | repository grant cache | Additive |
| 0013 | webhook delivery ledger | Additive |

---

## 6. Startup and rollback

**Startup** validates configuration before serving. On a missing required
setting the process refuses to boot and names the setting — never its value.
The worker performs the same check.

**Health endpoints:**

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness. Depends on nothing external — never GitHub. Use for restart probes. |
| `GET /ready` | Readiness. Checks PostgreSQL, Redis and configuration; reports auth mode, version and migration revision. Returns **503** when a dependency is down. |

Point restart probes at `/health` and load-balancer probes at `/ready`. A
liveness probe that failed on a Redis blip would restart a healthy process.

**Rollback:** deploy the previous image, then downgrade only if the release
included a migration. 0012 and 0013 downgrade cleanly. 0011's downgrade
**refuses** if two users share a project name — correctly, since restoring the
global constraint would mean deleting someone's project.

---

## 7. Requirements

- **PostgreSQL 16+** — the system of record. Never holds credentials.
- **Redis 7+** — sessions, single-use OAuth state, installation-token cache,
  rate-limit counters, and the arq job queue. **Losing Redis logs everyone out
  and clears cached tokens; it loses no durable data.**
