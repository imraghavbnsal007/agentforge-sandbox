# GitHub App Setup

Everything you must configure by hand on GitHub before `AUTH_MODE=github_app`
will work. Local mode needs none of this.

Create the App at **https://github.com/settings/apps/new**.

---

## 1. Identity

| Field | Value |
|---|---|
| GitHub App name | e.g. `AgentForge` — must be globally unique, so you may need a suffix |
| Homepage URL | dev `http://localhost:3000` / prod `https://<your-domain>` |

The App's **URL slug** (from `https://github.com/apps/<slug>`) goes in
`GITHUB_APP_NAME`. Without it the "Install GitHub App" link cannot be built.

---

## 2. URLs

| Field | Local development | Production |
|---|---|---|
| **Callback URL** | `http://localhost:8000/api/v1/auth/github/callback` | `https://<domain>/api/v1/auth/github/callback` |
| **Setup URL** | `http://localhost:8000/api/v1/github/setup` | `https://<domain>/api/v1/github/setup` |
| **Webhook URL** | `https://<tunnel-host>/api/v1/github/webhooks` | `https://<domain>/api/v1/github/webhooks` |

Three checkboxes matter:

- ✅ **Request user authorization (OAuth) during installation** — **required.**
  The no-token-retention design depends on GitHub returning `code` and
  `installation_id` in the same redirect. Without it, installation ownership
  cannot be verified without storing a user token.
- ✅ **Redirect on update** — so re-configuring an installation returns the user
  to AgentForge.
- ✅ **Active** under Webhooks.

Webhooks need a **public HTTPS URL**. `localhost` will not receive deliveries,
so local development requires a tunnel. Any provider works; the URL is
configuration, not code.

---

## 3. Permissions — least privilege

**Repository permissions:**

| Permission | Access | Why |
|---|---|---|
| Metadata | Read-only | Mandatory for any App |
| Contents | Read and write | Clone the repository; push the branch |
| Pull requests | Read and write | Open the PR |

**Nothing else.** Explicitly *not* requested: repository administration,
organisation permissions, members, secrets, or workflows. AgentForge refuses
an operation whose required permission is missing rather than asking for more
than it needs.

---

## 4. Webhook events

Subscribe to exactly two:

- **Installation**
- **Installation repositories**

These carry `created`, `deleted`, `suspend`, `unsuspend` and
`added` / `removed`. Any other event is answered `200` and ignored.

---

## 5. Installation scope

**"Where can this GitHub App be installed?" → Any account.**

Required for public multi-user use. Users choose *all* or *selected*
repositories at install time; AgentForge only ever sees what they grant.

---

## 6. Secrets to generate

1. **Client secret** — Generate, copy once. → `GITHUB_APP_CLIENT_SECRET`
2. **Webhook secret** — Generate a strong random string yourself. → `GITHUB_APP_WEBHOOK_SECRET`
3. **Private key** — "Generate a private key" downloads a `.pem`. → mount it and set `GITHUB_APP_PRIVATE_KEY_PATH`

The `.pem` is **never committed** — `*.pem` and `secrets/*` are gitignored. In
development drop it in `secrets/`, which is mounted read-only at
`/run/secrets`. In production mount a real secret.

---

## 7. Commit identity

`GITHUB_APP_COMMIT_NAME` and `GITHUB_APP_COMMIT_EMAIL` are **required** and
have no defaults on purpose: inventing a noreply address would attribute
commits to an identity that may not exist.

Use the App's bot identity:

```
GITHUB_APP_COMMIT_NAME=agentforge[bot]
GITHUB_APP_COMMIT_EMAIL=<bot-user-id>+agentforge[bot]@users.noreply.github.com
```

The bot user id comes from `https://api.github.com/users/<app-slug>%5Bbot%5D`.
AgentForge deliberately does not discover it automatically — that would be an
extra API call on a path that must stay fast and predictable.

---

## 8. Resulting configuration

```bash
AUTH_MODE=github_app

GITHUB_APP_NAME=agentforge-dev          # the URL slug
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=
GITHUB_APP_ID=                          # numeric, from the settings page
GITHUB_APP_PRIVATE_KEY_PATH=/run/secrets/agentforge-app.pem
GITHUB_APP_WEBHOOK_SECRET=
GITHUB_APP_COMMIT_NAME=agentforge[bot]
GITHUB_APP_COMMIT_EMAIL=...

GITHUB_APP_CALLBACK_URL=http://localhost:8000/api/v1/auth/github/callback
FRONTEND_URL=http://localhost:3000
CORS_ORIGINS=http://localhost:3000
```

Startup validation refuses to boot if any required value is missing, naming
the setting — never printing its value. See `docs/DEPLOYMENT.md`.

---

## 9. Verifying the setup

1. Start the stack, visit the frontend — you should be redirected to `/login`
2. Sign in with GitHub
3. Open **Repositories** → "Install GitHub App"
4. Choose an account and **one throwaway repository** for the first test
5. You are returned to AgentForge; the repository appears in discovery
6. Check `GET /ready` — `auth_mode` should read `github_app` and all checks pass

Use a throwaway repository for the first end-to-end run, never a repository
that matters.
