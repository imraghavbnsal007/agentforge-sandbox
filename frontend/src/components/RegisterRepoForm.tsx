"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { registerProject } from "@/lib/api";

export function RegisterRepoForm() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const project = await registerProject({
        repo_url: repoUrl,
        default_branch: branch,
      });
      setRepoUrl("");
      router.push(`/projects/${project.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-lg border border-slate-200 bg-white p-4"
    >
      <p className="mb-3 text-sm font-medium text-slate-700">
        Register a GitHub repository
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-72 flex-1">
          <label className="mb-1 block text-xs text-slate-500">Repository URL</label>
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            required
            placeholder="https://github.com/owner/repo"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
        </div>
        <div className="w-40">
          <label className="mb-1 block text-xs text-slate-500">Default branch</label>
          <input
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            required
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {busy ? "Validating…" : "Register"}
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-400">
        Registration only validates and saves the repo — analysis runs when you
        click Analyze (or create the first task).
      </p>
      {error && (
        <p className="mt-2 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}
    </form>
  );
}
