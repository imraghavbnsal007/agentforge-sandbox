import type { Metadata } from "next";
import { ChunkGuard } from "@/components/ChunkGuard";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentForge",
  description: "AI engineering assistant for feature requests",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <ChunkGuard />
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
            <span className="text-xl">⚒️</span>
            <h1 className="text-lg font-semibold tracking-tight">AgentForge</h1>
            <nav className="ml-6 flex items-center gap-4 text-sm text-slate-600">
              <a href="/" className="hover:text-slate-900">Dashboard</a>
              <a href="/projects" className="hover:text-slate-900">Projects</a>
              <a href="/tasks/new" className="hover:text-slate-900">New Task</a>
              <a href="/usage" className="hover:text-slate-900">Usage</a>
            </nav>
            <span className="ml-auto hidden text-sm text-slate-400 sm:block">
              AI engineering assistant
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
