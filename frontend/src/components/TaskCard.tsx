"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { motion } from "framer-motion";
import { ProviderBadge } from "@/components/ProviderBadge";
import { StatusBadge } from "@/components/StatusBadge";
import {
  IconBranch,
  IconClock,
  IconCoin,
  IconCopy,
  IconEye,
  IconExternal,
  IconRetry,
} from "@/components/ui/Icons";
import { Spinner } from "@/components/ui/Button";
import { retryTask, type Task, type TaskStatus } from "@/lib/api";
import { formatCost, formatDuration, timeAgo } from "@/lib/format";

/** How far along the pipeline each status is (drives the progress bar). */
const PROGRESS: Record<TaskStatus, number> = {
  pending: 6,
  planning: 25,
  coding: 55,
  testing: 78,
  ready_for_review: 90,
  publishing: 96,
  completed: 100,
  failed: 100,
  rejected: 100,
  cancelled: 100,
  publish_failed: 100,
};

const BAR_COLOR: Record<string, string> = {
  completed: "from-emerald-500 to-emerald-400",
  failed: "from-red-500 to-red-400",
  rejected: "from-slate-600 to-slate-500",
  ready_for_review: "from-violet-500 to-violet-400",
  default: "from-indigo-500 to-blue-400",
};

const FINISHED: TaskStatus[] = ["completed", "failed", "rejected"];
const RUNNING: TaskStatus[] = ["planning", "coding", "testing", "publishing"];

function ActionButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="rounded-lg border border-line-strong bg-surface-3 p-1.5 text-ink-mid transition-colors hover:border-[rgba(255,255,255,0.28)] hover:text-ink"
    >
      {children}
    </button>
  );
}

export function TaskCard({
  task,
  projectName,
  repo,
  estimatedCost,
  index = 0,
}: {
  task: Task;
  projectName: string;
  /** "owner/repo" when the project is GitHub-configured, else null. */
  repo: string | null;
  /** Profile-based cost estimate in USD; null when unknown/custom. */
  estimatedCost: number | null;
  index?: number;
}) {
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finished = FINISHED.includes(task.status);
  const running = RUNNING.includes(task.status);
  const progress = PROGRESS[task.status];
  const barColor =
    BAR_COLOR[task.status as keyof typeof BAR_COLOR] ?? BAR_COLOR.default;

  const duration = finished
    ? formatDuration(task.created_at, task.updated_at)
    : running
      ? formatDuration(task.created_at)
      : null;

  async function onRetry() {
    setRetrying(true);
    setError(null);
    try {
      await retryTask(task.id);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  }

  const duplicateHref = {
    pathname: "/tasks/new",
    query: { project: task.project_id, title: task.title, request: task.request },
  };

  return (
    <motion.article
      // Transform only — never opacity. See ProjectCard: an opacity entrance
      // can freeze at 0 when requestAnimationFrame is throttled in a
      // background tab, hiding the card entirely.
      initial={{ y: 14 }}
      animate={{ y: 0 }}
      transition={{ duration: 0.35, delay: Math.min(index * 0.05, 0.4), ease: "easeOut" }}
      className="card card-hover group relative flex flex-col gap-3 p-5 focus-within:border-line-strong"
    >
      {/* Header: title (the card's link) + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/tasks/${task.id}`}
            className="text-[15px] font-semibold leading-snug text-ink outline-none after:absolute after:inset-0 after:content-[''] hover:text-white"
          >
            {task.title}
          </Link>
          <p className="mt-1 line-clamp-1 text-xs text-ink-dim">{task.request}</p>
        </div>
        <StatusBadge status={task.status} />
      </div>

      {/* Badges: provider / model / profile */}
      <div className="flex flex-wrap items-center gap-1.5">
        {task.llm_provider ? (
          <ProviderBadge provider={task.llm_provider} model={task.llm_model} />
        ) : task.execution_profile ? (
          <span className="inline-flex items-center rounded-full bg-indigo-500/12 px-2.5 py-0.5 text-xs font-medium capitalize text-indigo-300 ring-1 ring-inset ring-indigo-400/25">
            {task.execution_profile} profile
          </span>
        ) : null}
        {task.llm_provider && task.execution_profile && (
          <span className="inline-flex items-center rounded-full bg-slate-500/12 px-2.5 py-0.5 text-xs font-medium capitalize text-slate-400 ring-1 ring-inset ring-slate-400/20">
            {task.execution_profile}
          </span>
        )}
        {task.latest_run_pr_url && (
          <a
            href={task.latest_run_pr_url}
            target="_blank"
            rel="noreferrer"
            className="relative z-10 inline-flex items-center gap-1 rounded-full bg-emerald-500/12 px-2.5 py-0.5 text-xs font-medium text-emerald-300 ring-1 ring-inset ring-emerald-400/25 hover:bg-emerald-500/20"
          >
            PR <IconExternal className="h-3 w-3" />
          </a>
        )}
      </div>

      {/* Meta row: repository · created · duration · cost */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-dim">
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <IconBranch className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{repo ?? projectName}</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <IconClock className="h-3.5 w-3.5" />
          {timeAgo(task.created_at)}
          {duration && <span className="text-ink-dim/70">· {duration}</span>}
        </span>
        <span
          className="inline-flex items-center gap-1.5"
          title="Estimated cost (execution profile estimate)"
        >
          <IconCoin className="h-3.5 w-3.5" />
          {task.execution_profile && estimatedCost != null
            ? `~${formatCost(estimatedCost)}`
            : "—"}
        </span>
      </div>

      {/* Progress */}
      <div
        className="h-1 w-full overflow-hidden rounded-full bg-surface-3"
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Task progress: ${task.status.replaceAll("_", " ")}`}
      >
        <motion.div
          className={`h-full rounded-full bg-gradient-to-r ${barColor} ${running ? "animate-pulse" : ""}`}
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>

      {/* Hover actions (also keyboard-reachable via focus-within) */}
      <div className="absolute right-4 top-12 z-10 flex gap-1.5 opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover:opacity-100">
        <Link
          href={`/tasks/${task.id}`}
          aria-label={`View task: ${task.title}`}
          title="View"
          className="rounded-lg border border-line-strong bg-surface-3 p-1.5 text-ink-mid transition-colors hover:border-[rgba(255,255,255,0.28)] hover:text-ink"
        >
          <IconEye className="h-3.5 w-3.5" />
        </Link>
        {finished && (
          <ActionButton label={`Retry task: ${task.title}`} onClick={onRetry}>
            {retrying ? <Spinner className="h-3.5 w-3.5" /> : <IconRetry className="h-3.5 w-3.5" />}
          </ActionButton>
        )}
        <Link
          href={duplicateHref}
          aria-label={`Duplicate task: ${task.title}`}
          title="Duplicate (prefills a new task)"
          className="rounded-lg border border-line-strong bg-surface-3 p-1.5 text-ink-mid transition-colors hover:border-[rgba(255,255,255,0.28)] hover:text-ink"
        >
          <IconCopy className="h-3.5 w-3.5" />
        </Link>
      </div>

      {error && <p className="relative z-10 text-xs text-red-400">{error}</p>}
    </motion.article>
  );
}
