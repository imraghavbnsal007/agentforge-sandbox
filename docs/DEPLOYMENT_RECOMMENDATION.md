# Deployment recommendation

How to show AgentForge publicly without handing strangers a coding agent
attached to your GitHub account.

## Recommendation

**Recorded demo, plus the repository, plus `SHOWCASE_MODE` only if you want a
live link.**

For a portfolio launch this gives the best ratio of impact to risk. A
60-second video shows the complete flow — including a real pull request being
opened — which no safe public deployment can do, because a safe public
deployment is precisely one that cannot write to GitHub.

| Option | Effort | Risk | Shows the full flow |
|---|---|---|---|
| **Recorded demo + repository** | Low | None | **Yes** |
| **Showcase mode, public** | Medium | Low | No — publishing is disabled |
| **Password-protected full deployment** | Medium | Medium | Yes, to whoever has the password |
| **Fully public, unrestricted** | High | **Unacceptable** | Yes |

### Why not a fully public unrestricted deployment

Anyone could register any repository, spend your API budget without limit,
run arbitrary repository test commands inside your worker container, and use
your GitHub App installation to open pull requests. Do not do this. It is not
a matter of hardening — the feature set is inherently privileged.

### Why showcase mode is the right *live* option

`SHOWCASE_MODE=true` refuses, server-side:

- publishing to GitHub (`POST /tasks/{id}/approve`)
- registering or cloning any repository
- repository analysis (which clones and spends API budget)
- changing project AI settings
- deleting tasks

and forces the deterministic mock agent regardless of `AGENT_MODE`, so no
visitor can spend money. Visitors can still create tasks against the bundled
sample repository and watch the whole pipeline run live — planning, tool
calls, diffs, tests — which is most of what makes the project interesting.

The gates are route dependencies, not hidden buttons. The UI hides the
controls too, but the enforcement is server-side because the case that
matters is someone with `curl`.

## If you deploy showcase mode

### Required environment

```bash
SHOWCASE_MODE=true
AGENT_MODE=mock            # forced anyway; set it so the config reads honestly
AUTH_MODE=local            # no sign-in friction for visitors
COOKIE_SECURE=true         # you will be on HTTPS
TRUST_PROXY_HEADERS=true   # only if behind a proxy that overwrites the header

NEXT_PUBLIC_API_URL=https://api.your-domain.example
FRONTEND_URL=https://your-domain.example
CORS_ORIGINS=https://your-domain.example

# Leave every one of these EMPTY. A showcase deployment needs none of them.
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
GITHUB_TOKEN=
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY_PATH=
```

Leaving the credentials empty is the real protection. Showcase mode should
be defence in depth, not the only thing standing between a visitor and your
API bill.

### Before exposing it

The shipped `docker-compose.yml` is a **development** configuration. At
minimum, change:

1. **Postgres password** — currently `agentforge` in plain text.
2. **`uvicorn --reload`** — remove it; add `--workers N`.
3. **Frontend** — `next build && next start`, not the dev server.
4. **TLS** — terminate at a reverse proxy; set `COOKIE_SECURE=true`.
5. **Restart policies and resource limits** — neither is set.
6. **Rate limiting** at the proxy — the app rate-limits auth endpoints only.
7. **A cleanup job** — visitors share one demo account, so tasks accumulate
   indefinitely. Truncate periodically.

### Known limitations of showcase mode

Stated plainly so nobody is surprised:

- **All visitors share one account** (`AUTH_MODE=local`) and therefore see
  each other's tasks. Acceptable for a demo; do not present it as
  multi-tenancy. The real multi-tenancy is in `github_app` mode.
- **The mock agent always makes the same edit.** It is a pipeline
  demonstration, not a capability demonstration. Say so in your post.
- **Nothing proves the GitHub integration works** — that is exactly what the
  recorded demo is for.

## If you choose password protection instead

Put HTTP Basic auth at the reverse proxy in front of everything, keep
`SHOWCASE_MODE=false`, and use a throwaway GitHub App installed on a single
disposable repository — never your real account. Share the password only with
people you would give repository access to anyway, because functionally that
is what you are doing.

## Suggested launch sequence

1. Record the demo locally, `AGENT_MODE=llm`, against a repository you own.
2. Capture the screenshots listed in [`LINKEDIN_SHOWCASE.md`](LINKEDIN_SHOWCASE.md).
3. Make the repository public. History has been verified free of secrets.
4. Post the video with the repository link.
5. Add the live showcase deployment later, if at all — the video is doing the
   persuading, and a link that breaks under a traffic spike works against you.
