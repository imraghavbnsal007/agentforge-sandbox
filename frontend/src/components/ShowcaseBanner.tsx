/**
 * Tells a visitor, before they touch anything, that this is a demonstration
 * and what it will not do.
 *
 * Shown on every page rather than once on the dashboard: someone arriving
 * from a deep link in a LinkedIn post should not have to infer why the
 * publish button is missing.
 */
export function ShowcaseBanner() {
  return (
    <div
      role="status"
      className="border-b border-indigo-400/25 bg-indigo-500/[0.09] px-4 py-2.5 text-center text-xs text-indigo-200 sm:px-8"
    >
      <span className="font-semibold">Portfolio Demo Mode</span>
      <span className="mx-2 text-indigo-300/40" aria-hidden>
        •
      </span>
      <span className="text-indigo-200/80">
        Tasks run against a bundled sample repository with a deterministic
        agent. Publishing to GitHub, repository registration and analysis are
        disabled.
      </span>
    </div>
  );
}
