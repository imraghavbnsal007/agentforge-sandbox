import Link from "next/link";
import { AnalysisStatusBadge } from "@/components/AnalysisStatusBadge";
import { AutoRefresh } from "@/components/AutoRefresh";
import { RegisterRepoForm } from "@/components/RegisterRepoForm";
import { getProjects } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ProjectsPage() {
  const projects = await getProjects();
  const anyActive = projects.some(
    (p) => p.analysis_status === "pending" || p.analysis_status === "running",
  );

  return (
    <div className="space-y-6">
      {anyActive && <AutoRefresh intervalMs={3000} />}
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Projects</h2>
        <p className="mt-1 text-sm text-slate-500">
          Registered repositories and what AgentForge knows about them
        </p>
      </div>

      <RegisterRepoForm />

      {projects.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No projects yet — register a repository above or run{" "}
          <code className="rounded bg-slate-100 px-1">make seed</code>.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {projects.map((p) => (
            <Link
              key={p.id}
              href={`/projects/${p.id}`}
              className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-300 hover:shadow-sm"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-slate-900">{p.name}</p>
                <AnalysisStatusBadge status={p.analysis_status} />
              </div>
              {p.repo_url ? (
                <p className="mt-1 truncate text-xs text-slate-500">
                  {p.repo_url.replace(/\.git$/, "")} · {p.default_branch}
                </p>
              ) : (
                <p className="mt-1 text-xs text-slate-400">
                  sample repo (local) — no GitHub configuration
                </p>
              )}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <dt className="text-slate-400">Language</dt>
                <dd className="text-slate-700">{p.primary_language ?? "—"}</dd>
                <dt className="text-slate-400">Framework</dt>
                <dd className="text-slate-700">{p.framework ?? "—"}</dd>
                <dt className="text-slate-400">Test command</dt>
                <dd className="truncate font-mono text-slate-700">
                  {p.test_command ?? "—"}
                </dd>
                <dt className="text-slate-400">Last analyzed</dt>
                <dd className="text-slate-700">
                  {p.last_analyzed_at
                    ? new Date(p.last_analyzed_at).toLocaleString()
                    : "never"}
                </dd>
              </dl>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
