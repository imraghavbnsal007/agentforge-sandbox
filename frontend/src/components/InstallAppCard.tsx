import { IconBranch, IconExternal } from "@/components/ui/Icons";

/**
 * Empty state for users with no GitHub App installation yet — the only route
 * to registering a repository in github_app mode.
 */
export function InstallAppCard({
  installUrl,
  appConfigured,
  manage = false,
}: {
  installUrl: string | null;
  appConfigured: boolean;
  /** Render as "manage access" rather than first-time install. */
  manage?: boolean;
}) {
  if (!appConfigured || !installUrl) {
    return (
      <div className="card p-6">
        <h3 className="text-sm font-semibold text-amber-300">
          The GitHub App is not configured on this server
        </h3>
        <p className="mt-2 text-xs leading-relaxed text-ink-dim">
          Set <code className="text-ink-mid">GITHUB_APP_ID</code>,{" "}
          <code className="text-ink-mid">GITHUB_APP_NAME</code> and{" "}
          <code className="text-ink-mid">GITHUB_APP_PRIVATE_KEY_PATH</code> to
          enable repository access, or run with{" "}
          <code className="text-ink-mid">AUTH_MODE=local</code> for single-user
          development.
        </p>
      </div>
    );
  }

  return (
    <div className="card p-6">
      <h3 className="text-[15px] font-semibold text-ink">
        {manage
          ? "Need a repository that isn't listed?"
          : "Install AgentForge on GitHub to begin"}
      </h3>
      <p className="mt-2 max-w-xl text-xs leading-relaxed text-ink-dim">
        {manage
          ? "Grant the GitHub App access to more repositories, or change which ones it can see. Only repositories you grant appear here."
          : "AgentForge can only see repositories you explicitly grant it. Choose an account or organisation, then pick the repositories it may read and open pull requests against."}
      </p>
      <a
        href={installUrl}
        target="_blank"
        rel="noreferrer"
        className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gradient-to-b from-indigo-500 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] transition-colors hover:from-indigo-400 hover:to-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
      >
        <IconBranch className="h-4 w-4" />
        {manage ? "Manage GitHub App access" : "Install GitHub App"}
        <IconExternal className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}
