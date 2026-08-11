# LinkedIn showcase materials

Everything needed to present AgentForge publicly: a recording sequence, a
screenshot list, and post copy.

Replace `<REPO_URL>` throughout with the public repository URL.

---

## 1. Sixty-second demo recording

Record at **1280×800** (readable when LinkedIn scales it down), in a clean
browser window — no bookmarks bar, no other tabs, no personal notifications.

**Before you hit record:**

- Run `AGENT_MODE=llm` against a repository you own and do not mind receiving
  a real pull request.
- Delete or hide unrelated demo tasks so the dashboard reads clearly.
- Have the task text already copied to your clipboard — nobody wants to watch
  typing.
- Do a full dry run first. The single most common failure is a live model
  taking longer than expected on camera.

| # | Time | Action | What the viewer should notice |
|---|---|---|---|
| 1 | 0:00–0:05 | Open the dashboard | A real product, not a terminal |
| 2 | 0:05–0:10 | Sign in with GitHub | Real OAuth, not a fake login |
| 3 | 0:10–0:15 | Repository picker | Only repositories *you granted* appear |
| 4 | 0:15–0:22 | Open a repository, show analysis | Detected languages, frameworks, test command |
| 5 | 0:22–0:28 | Create a task, paste the request | Plain English in |
| 6 | 0:28–0:34 | Generated plan appears | The agent states its intent before acting |
| 7 | 0:34–0:44 | Live execution | Stages and tool calls streaming in real time |
| 8 | 0:44–0:48 | Test results | It runs *the repository's own* suite |
| 9 | 0:48–0:54 | Scroll the diff | Reviewable, per-file, before anything is pushed |
| 10 | 0:54–0:57 | Click **Approve & Create PR** | The human decision point — linger here |
| 11 | 0:57–1:00 | Open the real pull request on GitHub | It genuinely worked |

**Editing notes**

- Speed up steps 7–8 by 2–4× with a "generating…" caption. Do not fake it —
  a visible speed-up is honest, a cut is not.
- Hold **step 10** a beat longer than feels natural. It is the whole argument
  of the project.
- Add captions: LinkedIn autoplays muted.
- Keep the total under 60 seconds. Native video outperforms a link.

**Do not record:** your `.env`, terminal scrollback containing keys, the
GitHub App settings page, or a private repository's contents.

---

## 2. Screenshots to capture

Save into `docs/images/` using exactly these names — the README already
references them.

| File | Shot | Why it earns its place |
|---|---|---|
| `dashboard.png` | Task board with several statuses | Shows it is a real application |
| `repositories.png` | Repository picker after App install | Scoped access, the security story |
| `analysis.png` | Analysis output for a repository | Depth beyond "call an LLM" |
| `execution.png` | Live execution mid-run | The streaming/real-time work |
| `diff.png` | Per-file diff at review | The human-in-the-loop moment |
| `pull-request.png` | The generated PR on GitHub | Proof of the end result |
| `usage.png` | Usage page with cost breakdown | Cost awareness reads as maturity |

Use light-on-dark as-is; crop tightly; redact repository names you would
rather not publish.

---

## 3. LinkedIn post

> I spent the last few months building AgentForge — an AI software
> engineering platform that analyses a repository, plans a change, writes the
> code, runs the tests, and opens a pull request.
>
> With one deliberate constraint: **it never touches your repository until a
> human approves the diff.**
>
> That constraint turned out to be the entire project. Writing an agent that
> edits code is a weekend. Writing one you would let near a real repository
> is not.
>
> What that actually required:
>
> → **Scoped credentials.** It is a GitHub App, not a pasted access token.
> OAuth establishes identity and is then discarded; repository access uses
> short-lived installation tokens, scoped to only the repositories a user
> explicitly granted.
>
> → **Surviving its own failures.** Long model calls meant runs that looked
> dead but weren't. That took distributed locks so a redelivered job cannot
> run twice, heartbeats to distinguish "still thinking" from "crashed", and a
> state machine that cannot contradict itself.
>
> → **Telling the truth when things break.** My favourite bug: the UI kept
> reporting "the worker stopped" for runs where the worker had never stopped.
> The error handler was crashing *while recording the error*, so the real
> cause never reached the database. Three bugs stacked into one confident,
> wrong message.
>
> The lesson I did not expect: most of the work in an autonomous system is
> not making it act. It is making it **stop**, **explain itself**, and **not
> lie to you when it fails**.
>
> Built with FastAPI, Next.js, PostgreSQL, Redis and Docker. 900+ backend
> tests, roughly one line of tests per line of code — which is the only
> reason I trusted any of the above.
>
> Code and architecture notes: <REPO_URL>
>
> #SoftwareEngineering #AI #Python #TypeScript #OpenSource

---

## 4. Short caption

> Built AgentForge: an AI agent that reads a repository, implements a change,
> runs the tests, and opens a pull request — but only after a human approves
> the diff.
>
> The interesting engineering wasn't making it act. It was making it stop,
> explain itself, and report failures honestly.
>
> FastAPI · Next.js · PostgreSQL · Redis · Docker
>
> <REPO_URL>

---

## 5. LinkedIn "Projects" section

**Title:** AgentForge — Human-in-the-Loop AI Software Engineering Platform

**Description:**

> A multi-tenant platform where an AI agent analyses a GitHub repository,
> plans and implements a requested change, runs the project's own test suite,
> and opens a pull request — gated behind explicit human approval of the
> diff.
>
> Built as a GitHub App with per-installation scoped tokens, keeping user
> identity (OAuth) strictly separate from repository authorisation. Handles
> long-running AI jobs with distributed execution locks, heartbeat-based
> crash recovery, an explicit task state machine, and live progress streaming
> over Server-Sent Events.
>
> Python · FastAPI · SQLAlchemy · PostgreSQL · Redis · arq · TypeScript ·
> Next.js · Docker. 919 backend and 76 frontend tests.

---

## 6. Answering "did you use AI to build this?"

You will be asked. The strong answer is yes, plus how you directed it:

- work was gated into phases requiring explicit approval before implementation;
- a destructive migration was blocked until rehearsed in an isolated database;
- the OAuth/installation-token separation was specified up front as a
  requirement, not discovered later;
- every bug fix required a regression test proven to fail without the fix.

That is engineering judgement, which is the thing worth hiring. Claiming
otherwise is both less impressive and easy to catch.
