import Link from "next/link";
import { notFound } from "next/navigation";
import { AnalysisStatusBadge } from "@/components/AnalysisStatusBadge";
import { AutoRefresh } from "@/components/AutoRefresh";
import { ReanalyzeButton } from "@/components/ReanalyzeButton";
import { getProject, type ProjectDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <h3 className="border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let project: ProjectDetail;
  try {
    project = await getProject(id);
  } catch {
    notFound();
  }

  const analysis = project.latest_analysis;
  const analyzing =
    analysis?.status === "pending" || analysis?.status === "running";
  const isGitHub = Boolean(project.repo_url);

  return (
    <div className="space-y-5">
      {analyzing && <AutoRefresh intervalMs={3000} />}

      <div>
        <Link
          href="/projects"
          className="text-sm text-slate-500 hover:text-slate-700"
        >
          ← All projects
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-semibold tracking-tight">{project.name}</h2>
          <AnalysisStatusBadge status={project.analysis_status} />
        </div>
        {project.repo_url && (
          <p className="mt-1 text-sm text-slate-500">
            <a
              href={project.repo_url.replace(/\.git$/, "")}
              target="_blank"
              rel="noreferrer"
              className="hover:underline"
            >
              {project.repo_url.replace(/\.git$/, "")}
            </a>{" "}
            · branch <code className="rounded bg-slate-100 px-1">{project.default_branch}</code>
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {isGitHub && !analyzing && (
            <ReanalyzeButton
              projectId={project.id}
              label={analysis ? "Re-analyze Repository" : "Analyze Repository"}
            />
          )}
          <Link
            href={`/tasks/new?project=${project.id}`}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            New Task
          </Link>
        </div>
      </div>

      {analysis?.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span className="font-medium">Analysis failed:</span> {analysis.error}
        </div>
      )}

      {analyzing && (
        <div className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          <span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
          Analyzing the repository — this page refreshes automatically.
        </div>
      )}

      {!analysis && isGitHub && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Not analyzed yet. Click <span className="font-medium">Analyze Repository</span>{" "}
          to detect the tech stack, test command, and improvement suggestions.
        </div>
      )}

      {analysis?.summary && (
        <Section title="Summary">
          <p className="whitespace-pre-wrap px-4 py-3 text-sm text-slate-700">
            {analysis.summary}
          </p>
        </Section>
      )}

      {analysis?.status === "completed" && (
        <Section title="Detected tech stack">
          <div className="space-y-3 px-4 py-3 text-sm">
            <div className="flex flex-wrap gap-1.5">
              {(analysis.languages ?? []).map((l) => (
                <span key={l} className="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-medium text-violet-700">
                  {l}
                </span>
              ))}
              {(analysis.frameworks ?? []).map((f) => (
                <span key={f} className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-medium text-sky-700">
                  {f}
                </span>
              ))}
              {analysis.package_manager && (
                <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                  {analysis.package_manager}
                </span>
              )}
            </div>
            <dl className="grid grid-cols-1 gap-x-8 gap-y-1 text-xs sm:grid-cols-2">
              <dt className="text-slate-400">Test command</dt>
              <dd className="font-mono text-slate-700">
                {analysis.test_command ?? "No automated test command detected."}
              </dd>
              <dt className="text-slate-400">Build command</dt>
              <dd className="font-mono text-slate-700">{analysis.build_command ?? "—"}</dd>
            </dl>
          </div>
        </Section>
      )}

      {analysis?.architecture_notes && (
        <Section title="Architecture">
          <p className="whitespace-pre-wrap px-4 py-3 text-sm text-slate-700">
            {analysis.architecture_notes}
          </p>
        </Section>
      )}

      {analysis?.risk_areas && (
        <Section title="Risks & weak areas">
          <p className="whitespace-pre-wrap px-4 py-3 text-sm text-slate-700">
            {analysis.risk_areas}
          </p>
        </Section>
      )}

      {analysis && analysis.file_summaries.length > 0 && (
        <Section title={`Important files (${analysis.file_summaries.length})`}>
          <table className="w-full text-left text-sm">
            <tbody className="divide-y divide-slate-100">
              {analysis.file_summaries.map((f) => (
                <tr key={f.id}>
                  <td className="px-4 py-2 font-mono text-xs text-slate-800">
                    {f.file_path}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">{f.file_type}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{f.purpose}</td>
                  <td className="px-4 py-2 text-right text-xs font-medium text-slate-400">
                    {f.importance_score}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {analysis && analysis.suggestions.length > 0 && (
        <Section title={`Suggested improvements (${analysis.suggestions.length})`}>
          <div className="divide-y divide-slate-100">
            {analysis.suggestions.map((s) => (
              <div key={s.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
                <div className="min-w-64 flex-1">
                  <p className="text-sm font-medium text-slate-900">
                    {s.title}{" "}
                    <span
                      className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${PRIORITY_STYLES[s.priority] ?? PRIORITY_STYLES.low}`}
                    >
                      {s.priority}
                    </span>
                    <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                      {s.category}
                    </span>
                  </p>
                  <p className="mt-0.5 text-xs text-slate-600">{s.description}</p>
                  {(s.related_files ?? []).length > 0 && (
                    <p className="mt-1 font-mono text-[11px] text-slate-400">
                      {(s.related_files ?? []).join(", ")}
                    </p>
                  )}
                </div>
                <Link
                  href={{
                    pathname: "/tasks/new",
                    query: {
                      project: project.id,
                      title: s.title,
                      request: `${s.description}${
                        (s.related_files ?? []).length
                          ? `\n\nRelated files: ${(s.related_files ?? []).join(", ")}`
                          : ""
                      }`,
                    },
                  }}
                  className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700"
                >
                  Create Task from Suggestion
                </Link>
              </div>
            ))}
          </div>
        </Section>
      )}

      {analysis?.analysis_logs && (
        <details className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-50">
            Analysis logs
          </summary>
          <pre className="max-h-72 overflow-y-auto border-t border-slate-200 bg-slate-900 px-4 py-3 text-xs leading-5 text-slate-300">
            {analysis.analysis_logs}
          </pre>
        </details>
      )}
    </div>
  );
}
