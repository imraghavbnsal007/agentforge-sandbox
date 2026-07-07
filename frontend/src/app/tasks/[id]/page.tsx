import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "react-markdown";
import { AutoRefresh } from "@/components/AutoRefresh";
import { DiffView } from "@/components/DiffView";
import { ModeBadge } from "@/components/ModeBadge";
import { RetryButton } from "@/components/RetryButton";
import { StatusBadge } from "@/components/StatusBadge";
import { getConfig, getTask, type TaskDetail } from "@/lib/api";

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

const ACTIVE_STATUSES = ["pending", "planning", "coding", "testing"];

export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let task: TaskDetail;
  try {
    task = await getTask(id);
  } catch {
    notFound();
  }
  const config = await getConfig();

  const run = task.latest_run;
  const tests = run?.test_results ?? [];
  const inProgress = ACTIVE_STATUSES.includes(task.status);
  const finished = task.status === "completed" || task.status === "failed";

  return (
    <div className="space-y-5">
      {inProgress && <AutoRefresh intervalMs={2000} />}

      <div>
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-700">
          ← Back to dashboard
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-semibold tracking-tight">{task.title}</h2>
          <StatusBadge status={task.status} />
          {run && (
            <ModeBadge
              mode={run.mode}
              model={run.mode === "llm" ? config.anthropic_model : undefined}
            />
          )}
          {finished && <RetryButton taskId={task.id} />}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Created {new Date(task.created_at).toLocaleString()}
          {task.runs.length > 1 && ` · ${task.runs.length} runs`}
        </p>
      </div>

      {run?.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span className="font-medium">Run failed:</span> {run.error}
        </div>
      )}

      <Section title="Request">
        <p className="whitespace-pre-wrap px-4 py-3 text-sm text-slate-700">
          {task.request}
        </p>
      </Section>

      {inProgress && !run?.plan && (
        <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">
          <span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
          The agent is working — this page refreshes automatically.
        </div>
      )}

      {run?.plan && (
        <Section title="Implementation plan">
          <ol className="list-decimal space-y-1.5 px-4 py-3 pl-9 text-sm text-slate-700">
            {run.plan.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </Section>
      )}

      {run?.log && (
        <Section title="Execution log">
          <pre className="max-h-72 overflow-y-auto bg-slate-900 px-4 py-3 text-xs leading-5 text-slate-300">
            {run.log}
          </pre>
        </Section>
      )}

      {run && run.file_changes.length > 0 && (
        <Section title={`Files changed (${run.file_changes.length})`}>
          <div className="divide-y divide-slate-200">
            {run.file_changes.map((change) => (
              <div key={change.id}>
                <div className="flex items-center gap-2 bg-slate-100 px-4 py-2">
                  <code className="text-xs font-medium text-slate-800">
                    {change.path}
                  </code>
                  <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-600">
                    {change.change_type}
                  </span>
                </div>
                <DiffView diff={change.diff} />
              </div>
            ))}
          </div>
        </Section>
      )}

      {tests.length > 0 && (
        <Section title="Test results">
          <div className="px-4 py-3">
            {tests.map((t) => (
              <div key={t.id} className="space-y-2">
                <div className="flex gap-2 text-xs font-medium">
                  <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-emerald-700">
                    {t.passed} passed
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-1 ${t.failed > 0 ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-500"}`}
                  >
                    {t.failed} failed
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-1 ${t.errored > 0 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"}`}
                  >
                    {t.errored} errored
                  </span>
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-500">
                    {t.duration}s · {t.suite}
                  </span>
                </div>
                {t.output && (
                  <pre className="max-h-56 overflow-y-auto rounded bg-slate-900 px-3 py-2 text-xs leading-5 text-slate-300">
                    {t.output}
                  </pre>
                )}
                {t.stderr && (
                  <pre className="max-h-40 overflow-y-auto rounded bg-red-950 px-3 py-2 text-xs leading-5 text-red-300">
                    {t.stderr}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {run?.summary && (
        <Section title="Summary">
          <div className="markdown px-4 py-3 text-sm text-slate-700">
            <Markdown>{run.summary}</Markdown>
          </div>
        </Section>
      )}

      {task.runs.length > 0 && (
        <details className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-50">
            View Raw Logs ({task.runs.length} run{task.runs.length > 1 ? "s" : ""})
          </summary>
          <div className="divide-y divide-slate-200 border-t border-slate-200">
            {[...task.runs].reverse().map((r) => (
              <div key={r.id}>
                <div className="flex flex-wrap items-center gap-2 bg-slate-100 px-4 py-2 text-xs text-slate-600">
                  <span className="font-medium">Run #{r.id}</span>
                  <ModeBadge mode={r.mode} />
                  <span
                    className={
                      r.status === "failed"
                        ? "font-medium text-red-600"
                        : r.status === "completed"
                          ? "font-medium text-emerald-600"
                          : "font-medium text-blue-600"
                    }
                  >
                    {r.status}
                  </span>
                  <span>
                    {new Date(r.started_at).toLocaleString()}
                    {r.finished_at &&
                      ` → ${new Date(r.finished_at).toLocaleTimeString()}`}
                  </span>
                </div>
                {r.error && (
                  <p className="border-b border-red-100 bg-red-50 px-4 py-2 text-xs text-red-700">
                    {r.error}
                  </p>
                )}
                <pre className="max-h-64 overflow-y-auto bg-slate-900 px-4 py-3 text-xs leading-5 text-slate-300">
                  {r.log ?? "(no log recorded)"}
                </pre>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
