import type { Metadata } from "next";
import { ChunkGuard } from "@/components/ChunkGuard";
import { Providers } from "@/components/Providers";
import { ShowcaseBanner } from "@/components/ShowcaseBanner";
import { Sidebar } from "@/components/Sidebar";
import { getConfig } from "@/lib/api";
import { getAuthStatus } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentForge",
  description: "AI engineering assistant for feature requests",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [auth, config] = await Promise.all([
    getAuthStatus(),
    // A failure here must not blank the whole app; the banner simply
    // does not render, which is the safe direction for a *missing* warning
    // only because showcase deployments set the flag deliberately.
    getConfig().catch(() => null),
  ]);

  return (
    <html lang="en">
      {/* suppressHydrationWarning: browser extensions (Grammarly, password
          managers) inject attributes onto <body> before React hydrates, which
          React then reports as a server/client mismatch. It is not our markup
          differing — scoped to this element only, so genuine mismatches
          anywhere else still surface. */}
      <body
        suppressHydrationWarning
        className="min-h-screen bg-surface-0 font-sans text-ink antialiased"
      >
        <ChunkGuard />
        <Providers>
          {config?.showcase_mode && <ShowcaseBanner />}
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface-3 focus:px-4 focus:py-2 focus:text-sm focus:text-ink"
          >
            Skip to content
          </a>
          <div className="flex min-h-screen flex-col md:flex-row">
            {/* Signed-out visitors get the bare landing shell — no navigation
                into data they cannot read. */}
            {auth.authenticated && <Sidebar user={auth.user} />}
            <main
              id="main-content"
              className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-8 sm:py-10"
            >
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
