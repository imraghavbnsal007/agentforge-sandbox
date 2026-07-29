/**
 * Explains the outcome of a GitHub App install round trip.
 *
 * The backend redirects here with a code rather than a message so that the
 * wording lives with the rest of the UI copy, and so a crafted query string
 * cannot put arbitrary text on the page.
 */

const MESSAGES: Record<string, { tone: "warn" | "info"; title: string; body: string }> = {
  not_available: {
    tone: "warn",
    title: "GitHub did not list that installation under your account",
    body: "If you installed AgentForge on an organisation, an owner may still need to approve it. Otherwise, install it again and make sure you are signed in to the same GitHub account.",
  },
  verification_failed: {
    tone: "warn",
    title: "AgentForge could not verify that installation with GitHub",
    body: "Nothing was linked. Try installing again — if it keeps failing, check the server can reach api.github.com.",
  },
  pending: {
    tone: "info",
    title: "Your installation request was sent for approval",
    body: "An owner of that organisation needs to approve AgentForge. Its repositories appear here once they do.",
  },
};

export function InstallNotice({ code }: { code: string | undefined }) {
  const message = code ? MESSAGES[code] : undefined;
  if (!message) return null;

  const warn = message.tone === "warn";
  return (
    <div
      role="status"
      className={`card p-4 ring-1 ring-inset ${
        warn ? "ring-amber-400/25" : "ring-indigo-400/25"
      }`}
    >
      <h3
        className={`text-sm font-semibold ${
          warn ? "text-amber-300" : "text-indigo-300"
        }`}
      >
        {message.title}
      </h3>
      <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-ink-dim">
        {message.body}
      </p>
    </div>
  );
}
