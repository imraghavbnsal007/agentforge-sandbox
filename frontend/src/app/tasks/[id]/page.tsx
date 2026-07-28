import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "react-markdown";
import { AutoRefresh } from "@/components/AutoRefresh";
import { TaskLivePanel } from "@/components/TaskLivePanel";
import { DiffView } from "@/components/DiffView";
import { ModeBadge } from "@/components/ModeBadge";
import { RetryButton } from "@/components/RetryButton";
import { ReviewActions } from "@/components/ReviewActions";
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
    <section className="card overflow-hidden">
      <h3 className="border-b border-line bg-surface-2/60 px-5 py-3 text-xs font-semibold uppercase tracking-wider text-ink-dim">
        {title}
      </h3>
      {children}
    </section>
  );
}

const ACTIVE_STATUSES = ["pending", "planning", "coding", "testing", "publishing"];

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
  const finished = ["completed", "failed", "rejected"].includes(task.status);

  return (
    <div className="space-y-5">
      {/* The live panel streams events and triggers its own refresh when a
          run reaches a milestone, so blanket polling is only a fallback for
          the rest of the page. */}
      {inProgress && <AutoRefresh intervalMs={5000} />}

      <div>
        <Link
          href="/"
          className="text-sm text-ink-dim transition-colors hover:text-ink-mid"
        >
          ← Back to dashboard
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">
            {task.title}
          </h2>
          <StatusBadge status={task.status} />
          {run && (
            <ModeBadge
              mode={run.mode}
              provider={run.llm_provider ?? undefined}
              model={
                run.mode === "llm"
                  ? (run.llm_model ?? config.anthropic_model)
                  : undefined
              }
            />
          )}
          {finished && <RetryButton taskId={task.id} />}
        </div>
        <p className="mt-1 text-sm text-ink-dim">
          Created {new Date(task.created_at).toLocaleString()}
          {task.runs.length > 1 && ` · ${task.runs.length} runs`}
        </p>
      </div>

      <TaskLivePanel
        taskId={task.id}
        status={task.status}
        startedAt={run?.started_at ?? task.created_at}
      />

      {run?.error && (
        <div className="card border-red-500/30 bg-red-500/[0.06] px-5 py-3 text-sm text-red-300">
          <span className="font-medium">
            {task.status === "ready_for_review" ? "Publish failed:" : "Run failed:"}
          </span>{" "}
          {run.error}
        </div>
      )}

      {task.status === "ready_for_review" &&
        run &&
        run.test_results.length === 0 && (
          <div className="card border-amber-500/30 bg-amber-500/[0.06] px-5 py-3 text-sm text-amber-300">
            <span className="font-medium">No automated test command detected.</span>{" "}
            These changes have not been verified by tests — review the diff
            carefully before approving.
          </div>
        )}

      {task.status === "ready_for_review" && <ReviewActions taskId={task.id} />}

      {task.status === "publishing" && (
        <div className="card flex items-center gap-3 border-cyan-500/30 bg-cyan-500/[0.06] px-5 py-3 text-sm text-cyan-300">
          <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" aria-hidden />
          Publishing — cloning, applying changes, pushing, and opening the pull request…
        </div>
      )}

      {run?.pr_url && (
        <div className="card border-emerald-500/30 bg-emerald-500/[0.06] px-5 py-4">
          <p className="text-sm font-medium text-emerald-300">Pull request created</p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            <span className="rounded-lg bg-surface-3 px-2 py-1 font-mono text-ink-mid ring-1 ring-inset ring-line-strong">
              {run.branch_name}
            </span>
            <span className="rounded-lg bg-surface-3 px-2 py-1 font-mono text-ink-mid ring-1 ring-inset ring-line-strong">
              {run.commit_sha?.slice(0, 10)}
            </span>
            <a
              href={run.pr_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 px-3 py-1.5 font-medium text-white shadow-[0_4px_14px_-4px_rgba(16,185,129,0.5)] transition-all hover:from-emerald-400 hover:to-emerald-600"
            >
              View Pull Request →
            </a>
          </div>
        </div>
      )}

      <Section title="Request">
        <p className="whitespace-pre-wrap px-5 py-4 text-sm leading-relaxed text-ink-mid">
          {task.request}
        </p>
      </Section>

      {inProgress && !run?.plan && (
        <div className="card flex items-center gap-3 px-5 py-6 text-sm text-ink-dim">
          <span className="relative flex h-2 w-2" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-400" />
          </span>
          The agent is working — this page refreshes automatically.
        </div>
      )}

      {run?.plan && (
        <Section title="Implementation plan">
          <ol className="list-decimal space-y-1.5 px-5 py-4 pl-10 text-sm text-ink-mid">
            {run.plan.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </Section>
      )}

      {run?.log && (
        <Section title="Execution log">
          <pre className="max-h-72 overflow-y-auto bg-[#07070c] px-5 py-3 text-xs leading-5 text-ink-mid">
            {run.log}
          </pre>
        </Section>
      )}

      {run && run.file_changes.length > 0 && (
        <Section title={`Files changed (${run.file_changes.length})`}>
          <div className="divide-y divide-line">
            {run.file_changes.map((change) => (
              <div key={change.id}>
                <div className="flex items-center gap-2 bg-surface-2 px-5 py-2">
                  <code className="text-xs font-medium text-ink">
                    {change.path}
                  </code>
                  <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-medium uppercase text-ink-dim ring-1 ring-inset ring-line">
                    {change.change_type}
                  </span>
                  {change.is_binary && (
                    <span className="rounded bg-amber-500/12 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-300 ring-1 ring-inset ring-amber-400/25">
                      binary
                    </span>
                  )}
                </div>
                {change.is_binary ? (
                  <div className="bg-surface-2/50 px-5 py-3 text-xs text-ink-dim">
                    Binary file changed — textual diff unavailable.
                    {change.size_bytes != null && (
                      <span className="ml-2">
                        {(change.size_bytes / 1024).toFixed(1)} KB
                      </span>
                    )}
                    {change.content_hash && (
                      <span className="ml-2 font-mono">
                        sha256:{change.content_hash.slice(0, 12)}…
                      </span>
                    )}
                  </div>
                ) : (
                  <DiffView diff={change.diff} />
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {tests.length > 0 && (
        <Section title="Test results">
          <div className="px-5 py-4">
            {tests.map((t) => (
              <div key={t.id} className="space-y-2">
                <div className="flex flex-wrap gap-2 text-xs font-medium">
                  <span className="rounded-full bg-emerald-500/12 px-2.5 py-1 text-emerald-300 ring-1 ring-inset ring-emerald-400/25">
                    {t.passed} passed
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-1 ring-1 ring-inset ${t.failed > 0 ? "bg-red-500/12 text-red-300 ring-red-400/25" : "bg-surface-3 text-ink-dim ring-line"}`}
                  >
                    {t.failed} failed
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-1 ring-1 ring-inset ${t.errored > 0 ? "bg-amber-500/12 text-amber-300 ring-amber-400/25" : "bg-surface-3 text-ink-dim ring-line"}`}
                  >
                    {t.errored} errored
                  </span>
                  <span className="rounded-full bg-surface-3 px-2.5 py-1 text-ink-dim ring-1 ring-inset ring-line">
                    {t.duration}s · {t.suite}
                  </span>
                </div>
                {t.output && (
                  <pre className="max-h-56 overflow-y-auto rounded-lg border border-line bg-[#07070c] px-3 py-2 text-xs leading-5 text-ink-mid">
                    {t.output}
                  </pre>
                )}
                {t.stderr && (
                  <pre className="max-h-40 overflow-y-auto rounded-lg border border-red-500/20 bg-red-950/40 px-3 py-2 text-xs leading-5 text-red-300">
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
          <div className="markdown px-5 py-4 text-sm text-ink-mid">
            <Markdown>{run.summary}</Markdown>
          </div>
        </Section>
      )}

      {task.runs.length > 0 && (
        <details className="card overflow-hidden">
          <summary className="cursor-pointer select-none px-5 py-3 text-xs font-semibold uppercase tracking-wider text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink-mid">
            View Raw Logs ({task.runs.length} run{task.runs.length > 1 ? "s" : ""})
          </summary>
          <div className="divide-y divide-line border-t border-line">
            {[...task.runs].reverse().map((r) => (
              <div key={r.id}>
                <div className="flex flex-wrap items-center gap-2 bg-surface-2 px-5 py-2 text-xs text-ink-mid">
                  <span className="font-medium text-ink">Run #{r.id}</span>
                  <ModeBadge
                    mode={r.mode}
                    provider={r.llm_provider ?? undefined}
                    model={r.llm_model ?? undefined}
                  />
                  <span
                    className={
                      r.status === "failed"
                        ? "font-medium text-red-400"
                        : r.status === "completed"
                          ? "font-medium text-emerald-400"
                          : "font-medium text-blue-400"
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
                  <p className="border-b border-red-500/20 bg-red-500/[0.06] px-5 py-2 text-xs text-red-300">
                    {r.error}
                  </p>
                )}
                <pre className="max-h-64 overflow-y-auto bg-[#07070c] px-5 py-3 text-xs leading-5 text-ink-mid">
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
