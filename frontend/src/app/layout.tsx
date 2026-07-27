import type { Metadata } from "next";
import { ChunkGuard } from "@/components/ChunkGuard";
import { Providers } from "@/components/Providers";
import { Sidebar } from "@/components/Sidebar";
import { getAuthStatus } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentForge",
  description: "AI engineering assistant for feature requests",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const auth = await getAuthStatus();

  return (
    <html lang="en">
      <body className="min-h-screen bg-surface-0 font-sans text-ink antialiased">
        <ChunkGuard />
        <Providers>
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
