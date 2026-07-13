"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
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
    <form onSubmit={onSubmit} className="card p-5">
      <p className="mb-3 text-sm font-medium text-ink">
        Register a GitHub repository
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-full flex-1 sm:min-w-72">
          <label htmlFor="repo-url" className="mb-1 block text-xs text-ink-dim">
            Repository URL
          </label>
          <input
            id="repo-url"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            required
            placeholder="https://github.com/owner/repo"
            className="field"
          />
        </div>
        <div className="w-40">
          <label htmlFor="repo-branch" className="mb-1 block text-xs text-ink-dim">
            Default branch
          </label>
          <input
            id="repo-branch"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            required
            className="field"
          />
        </div>
        <Button type="submit" loading={busy}>
          {busy ? "Validating…" : "Register"}
        </Button>
      </div>
      <p className="mt-2 text-xs text-ink-dim">
        Registration only validates and saves the repo — analysis runs when you
        click Analyze (or create the first task).
      </p>
      {error && (
        <p className="mt-2 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300 ring-1 ring-inset ring-red-400/25">
          {error}
        </p>
      )}
    </form>
  );
}
