import Link from "next/link";
import { notFound } from "next/navigation";
import { AnalysisStatusBadge } from "@/components/AnalysisStatusBadge";
import { AutoRefresh } from "@/components/AutoRefresh";
import { HealthScore } from "@/components/HealthScore";
import { ReanalyzeButton } from "@/components/ReanalyzeButton";
import { RepoMapTree } from "@/components/RepoMapTree";
import { ProjectAISettings } from "@/components/ProjectAISettings";
import { buttonClasses } from "@/components/ui/Button";
import { getLLMOptions, getProject, type ProjectDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="card overflow-hidden">
      <h3 className="border-b border-line bg-surface-2/60 px-5 py-3 text-xs font-semibold uppercase tracking-wider text-ink-dim">
        {title}
      </h3>
      {children}
    </section>
  );
}

const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-red-500/12 text-red-300 ring-1 ring-inset ring-red-400/25",
  medium: "bg-amber-500/12 text-amber-300 ring-1 ring-inset ring-amber-400/25",
  low: "bg-slate-500/12 text-slate-400 ring-1 ring-inset ring-slate-400/20",
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
  const llmOptions = await getLLMOptions();

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
          className="text-sm text-ink-dim transition-colors hover:text-ink-mid"
        >
          ← All projects
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">
            {project.name}
          </h2>
          <AnalysisStatusBadge
            status={project.analysis_status}
            warning={Boolean(analysis?.enrichment_warning)}
          />
          {analysis?.project_type && (
            <span className="rounded-full bg-surface-3 px-2.5 py-0.5 text-xs font-medium text-ink-mid ring-1 ring-inset ring-line-strong">
              {analysis.project_type}
            </span>
          )}
        </div>
        {project.repo_url && (
          <p className="mt-1 text-sm text-ink-dim">
            <a
              href={project.repo_url.replace(/\.git$/, "")}
              target="_blank"
              rel="noreferrer"
              className="transition-colors hover:text-ink-mid hover:underline"
            >
              {project.repo_url.replace(/\.git$/, "")}
            </a>{" "}
            · branch{" "}
            <code className="rounded bg-surface-3 px-1.5 py-0.5 text-xs">
              {project.default_branch}
            </code>
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
            className={buttonClasses("secondary")}
          >
            New Task
          </Link>
        </div>
      </div>

      <Section title="AI settings (defaults for new tasks)">
        <ProjectAISettings project={project} options={llmOptions} />
      </Section>

      {analysis?.error && (
        <div className="card border-red-500/30 bg-red-500/[0.06] px-5 py-3 text-sm text-red-300">
          <span className="font-medium">Analysis failed:</span> {analysis.error}
        </div>
      )}

      {analysis?.enrichment_warning && !analyzing && (
        <div className="card border-amber-500/30 bg-amber-500/[0.06] px-5 py-3 text-sm text-amber-300">
          <span className="font-medium">Partial analysis:</span> Repository facts
          were analyzed successfully, but AI enrichment could not be parsed. Use{" "}
          <span className="font-medium">Re-analyze Repository</span> to retry.
        </div>
      )}

      {analyzing && (
        <div className="card flex items-center gap-3 border-blue-500/30 bg-blue-500/[0.06] px-5 py-3 text-sm text-blue-300">
          <span className="relative flex h-2 w-2" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-400" />
          </span>
          Analyzing the repository — this page refreshes automatically.
        </div>
      )}

      {!analysis && isGitHub && (
        <div className="card border-dashed p-10 text-center text-sm text-ink-dim">
          Not analyzed yet. Click{" "}
          <span className="font-medium text-ink-mid">Analyze Repository</span> to
          detect the tech stack, test command, and improvement suggestions.
        </div>
      )}

      {analysis?.summary && (
        <Section title="Summary">
          <p className="whitespace-pre-wrap px-5 py-4 text-sm leading-relaxed text-ink-mid">
            {analysis.summary}
          </p>
        </Section>
      )}

      {analysis?.health_score != null && analysis.health_breakdown && (
        <Section title={`Repository health — ${analysis.health_score}/100`}>
          <HealthScore
            overall={analysis.health_score}
            breakdown={analysis.health_breakdown}
          />
        </Section>
      )}

      {analysis?.status === "completed" && (
        <Section title="Detected tech stack">
          <div className="space-y-3 px-5 py-4 text-sm">
            <div className="flex flex-wrap gap-1.5">
              {(analysis.languages ?? []).map((l) => (
                <span
                  key={l}
                  className="rounded-full bg-violet-500/12 px-2.5 py-0.5 text-xs font-medium text-violet-300 ring-1 ring-inset ring-violet-400/25"
                >
                  {l}
                </span>
              ))}
              {(analysis.frameworks ?? []).map((f) => (
                <span
                  key={f}
                  className="rounded-full bg-sky-500/12 px-2.5 py-0.5 text-xs font-medium text-sky-300 ring-1 ring-inset ring-sky-400/25"
                >
                  {f}
                </span>
              ))}
              {analysis.package_manager && (
                <span className="rounded-full bg-surface-3 px-2.5 py-0.5 text-xs font-medium text-ink-dim ring-1 ring-inset ring-line">
                  {analysis.package_manager}
                </span>
              )}
            </div>
            <dl className="grid grid-cols-1 gap-x-8 gap-y-1 text-xs sm:grid-cols-2">
              <dt className="text-ink-dim">Test command</dt>
              <dd className="font-mono text-ink-mid">
                {analysis.test_command ?? "No automated test command detected."}
              </dd>
              <dt className="text-ink-dim">Build command</dt>
              <dd className="font-mono text-ink-mid">
                {analysis.build_command ?? "—"}
              </dd>
            </dl>
          </div>
        </Section>
      )}

      {analysis?.architecture_notes && (
        <Section title="Architecture">
          <p className="whitespace-pre-wrap px-5 py-4 text-sm leading-relaxed text-ink-mid">
            {analysis.architecture_notes}
          </p>
        </Section>
      )}

      {analysis?.sql_schema && (
        <Section title="Database schema">
          <div className="px-5 py-4">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-ink-dim">
                  <tr>
                    <th className="py-1 pr-4 font-medium">Table</th>
                    <th className="py-1 pr-4 font-medium">Columns</th>
                    <th className="py-1 pr-4 font-medium">Primary key</th>
                    <th className="py-1 pr-4 font-medium">FKs</th>
                    <th className="py-1 pr-4 font-medium">Checks</th>
                    <th className="py-1 font-medium">File</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {analysis.sql_schema.tables.map((t) => (
                    <tr key={t.name}>
                      <td className="py-1.5 pr-4 font-mono text-xs font-medium text-ink">
                        {t.name}
                      </td>
                      <td className="py-1.5 pr-4 text-xs text-ink-mid">
                        {t.columns.length}
                      </td>
                      <td className="py-1.5 pr-4 font-mono text-xs text-ink-mid">
                        {t.primary_key.length ? (
                          t.primary_key.join(", ")
                        ) : (
                          <span className="font-sans font-medium text-red-400">
                            none
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 pr-4 text-xs text-ink-mid">
                        {t.foreign_keys.length}
                      </td>
                      <td className="py-1.5 pr-4 text-xs text-ink-mid">
                        {t.checks.length}
                      </td>
                      <td className="py-1.5 font-mono text-[11px] text-ink-dim">
                        {t.file}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-ink-dim">
              <span>{analysis.sql_schema.views.length} views</span>·
              <span>{analysis.sql_schema.procedures.length} procedures</span>·
              <span>{analysis.sql_schema.functions.length} functions</span>·
              <span>{analysis.sql_schema.triggers.length} triggers</span>·
              <span>{analysis.sql_schema.indexes.length} indexes</span>
            </div>
            {analysis.sql_schema.dropped_views_not_created.length > 0 && (
              <p className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-300 ring-1 ring-inset ring-amber-400/25">
                Dropped but never created:{" "}
                {analysis.sql_schema.dropped_views_not_created.join(", ")}
              </p>
            )}
            {analysis.schema_summary && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs font-medium text-ink-dim transition-colors hover:text-ink-mid">
                  Full schema summary
                </summary>
                <pre className="mt-2 max-h-72 overflow-y-auto rounded-lg border border-line bg-[#07070c] px-3 py-2 text-xs leading-5 text-ink-mid">
                  {analysis.schema_summary}
                </pre>
              </details>
            )}
          </div>
        </Section>
      )}

      {analysis?.repo_map && analysis.repo_map.length > 0 && (
        <Section title="Repository map">
          <RepoMapTree nodes={analysis.repo_map} />
        </Section>
      )}

      {((analysis?.entry_points?.length ?? 0) > 0 ||
        (analysis?.api_routes?.length ?? 0) > 0) && (
        <Section title="Entry points & API routes">
          <div className="space-y-2 px-5 py-4 text-sm">
            {analysis?.entry_points?.map((e) => (
              <code
                key={e}
                className="mr-2 rounded bg-surface-3 px-2 py-0.5 text-xs text-ink-mid ring-1 ring-inset ring-line"
              >
                {e}
              </code>
            ))}
            {(analysis?.api_routes ?? []).map((r, i) => (
              <p key={i} className="font-mono text-xs text-ink-mid">
                <span className="font-semibold text-ink">{r.method}</span> {r.path}{" "}
                <span className="text-ink-dim">({r.file})</span>
              </p>
            ))}
          </div>
        </Section>
      )}

      {analysis?.risk_areas && (
        <Section title="Risks & weak areas">
          <p className="whitespace-pre-wrap px-5 py-4 text-sm leading-relaxed text-ink-mid">
            {analysis.risk_areas}
          </p>
        </Section>
      )}

      {analysis && analysis.file_summaries.length > 0 && (
        <Section title={`Important files (${analysis.file_summaries.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <tbody className="divide-y divide-line">
                {analysis.file_summaries.map((f) => (
                  <tr key={f.id}>
                    <td className="px-5 py-2 font-mono text-xs text-ink">
                      {f.file_path}
                    </td>
                    <td className="px-4 py-2 text-xs text-ink-dim">{f.file_type}</td>
                    <td className="px-4 py-2 text-xs text-ink-mid">{f.purpose}</td>
                    <td className="px-5 py-2 text-right text-xs font-medium tabular-nums text-ink-dim">
                      {f.importance_score}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {analysis && analysis.suggestions.length > 0 && (
        <Section title={`Suggested improvements (${analysis.suggestions.length})`}>
          <div className="divide-y divide-line">
            {analysis.suggestions.map((s) => (
              <div key={s.id} className="flex flex-wrap items-start gap-3 px-5 py-4">
                <div className="min-w-64 flex-1">
                  <p className="text-sm font-medium text-ink">
                    {s.title}{" "}
                    <span
                      className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${PRIORITY_STYLES[s.priority] ?? PRIORITY_STYLES.low}`}
                    >
                      {s.priority}
                    </span>
                    <span className="ml-1 rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-ink-dim ring-1 ring-inset ring-line">
                      {s.category}
                    </span>
                    <span className="ml-1 rounded-full bg-indigo-500/12 px-2 py-0.5 text-[10px] text-indigo-300 ring-1 ring-inset ring-indigo-400/25">
                      confidence: {s.confidence}
                    </span>
                    <span className="ml-1 rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-ink-dim ring-1 ring-inset ring-line">
                      effort: {s.effort}
                    </span>
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-ink-mid">
                    {s.description}
                  </p>
                  {s.reasoning && (
                    <p className="mt-1 text-[11px] italic leading-4 text-ink-dim">
                      Why: {s.reasoning}
                    </p>
                  )}
                  {(s.related_files ?? []).length > 0 && (
                    <p className="mt-1 font-mono text-[11px] text-ink-dim">
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
                  className={buttonClasses("secondary", "sm")}
                >
                  Create Task from Suggestion
                </Link>
              </div>
            ))}
          </div>
        </Section>
      )}

      {analysis?.analysis_logs && (
        <details className="card overflow-hidden">
          <summary className="cursor-pointer select-none px-5 py-3 text-xs font-semibold uppercase tracking-wider text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink-mid">
            Analysis logs
          </summary>
          <pre className="max-h-72 overflow-y-auto border-t border-line bg-[#07070c] px-5 py-3 text-xs leading-5 text-ink-mid">
            {analysis.analysis_logs}
          </pre>
        </details>
      )}
    </div>
  );
}
