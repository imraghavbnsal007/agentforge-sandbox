import { redirect } from "next/navigation";

import { IconBranch, IconSpark, Logo } from "@/components/ui/Icons";
import { getAuthStatus, loginUrl } from "@/lib/session";

export const dynamic = "force-dynamic";

const FEATURES = [
  {
    title: "Understands your repository",
    body: "Detects the stack, maps the structure, scores health, and surfaces grounded, file-specific suggestions.",
  },
  {
    title: "Ships real pull requests",
    body: "Plans, edits, and runs your test suite in an isolated workspace — then opens a PR you review before anything merges.",
  },
  {
    title: "You approve every change",
    body: "Nothing reaches your repository until you have read the diff and approved it.",
  },
];

export default async function LoginPage() {
  const auth = await getAuthStatus();
  if (auth.authenticated) redirect("/");

  return (
    <div className="mx-auto flex min-h-[80vh] max-w-3xl flex-col justify-center gap-10 py-12">
      <header className="space-y-4">
        <Logo className="h-11 w-11" />
        <h1 className="text-3xl font-semibold tracking-tight text-ink">
          AgentForge
        </h1>
        <p className="max-w-xl text-[15px] leading-relaxed text-ink-mid">
          An AI engineering agent for your own repositories. It reads the code,
          plans a change, writes it, runs the tests, and opens a pull request —
          with a review gate you control.
        </p>
      </header>

      <div className="card p-6">
        {auth.login_available ? (
          <>
            <a
              href={loginUrl("/")}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-b from-indigo-500 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] transition-colors hover:from-indigo-400 hover:to-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
            >
              <IconBranch className="h-4 w-4" />
              Sign in with GitHub
            </a>
            <p className="mt-3 text-xs text-ink-dim">
              AgentForge only reads your GitHub profile to identify you.
              Repository access is granted separately, per repository, when you
              install the GitHub App.
            </p>
          </>
        ) : (
          <div className="space-y-2">
            <p className="text-sm font-medium text-amber-300">
              GitHub sign-in is not configured on this server.
            </p>
            <p className="text-xs text-ink-dim">
              Set <code className="text-ink-mid">GITHUB_APP_CLIENT_ID</code> and{" "}
              <code className="text-ink-mid">GITHUB_APP_CLIENT_SECRET</code>, or
              run with <code className="text-ink-mid">AUTH_MODE=local</code> for
              single-user development.
            </p>
          </div>
        )}
      </div>

      <ul className="grid gap-4 sm:grid-cols-3">
        {FEATURES.map((feature) => (
          <li key={feature.title} className="card p-4">
            <IconSpark className="h-4 w-4 text-indigo-300" />
            <h2 className="mt-2 text-sm font-semibold text-ink">
              {feature.title}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-dim">
              {feature.body}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
