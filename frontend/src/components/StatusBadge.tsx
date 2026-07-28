import type { TaskStatus } from "@/lib/api";

/* Color groups: completed=emerald · running=blue · queued=orange ·
   failed=red · cancelled/rejected=gray · review=violet. */
const STYLES: Record<TaskStatus, string> = {
  pending: "bg-orange-500/12 text-orange-300 ring-orange-400/25",
  planning: "bg-blue-500/12 text-blue-300 ring-blue-400/25",
  coding: "bg-blue-500/12 text-blue-300 ring-blue-400/25",
  testing: "bg-blue-500/12 text-blue-300 ring-blue-400/25",
  publishing: "bg-blue-500/12 text-blue-300 ring-blue-400/25",
  ready_for_review: "bg-violet-500/12 text-violet-300 ring-violet-400/25",
  cancelled:
    "bg-slate-500/12 text-slate-300 ring-slate-400/25",
  publish_failed:
    "bg-red-500/12 text-red-300 ring-red-400/25",
  rejected: "bg-slate-500/12 text-slate-400 ring-slate-400/20",
  completed: "bg-emerald-500/12 text-emerald-300 ring-emerald-400/25",
  failed: "bg-red-500/12 text-red-300 ring-red-400/25",
};

const ACTIVE: TaskStatus[] = ["planning", "coding", "testing", "publishing"];

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status]}`}
    >
      {ACTIVE.includes(status) && (
        <span className="relative flex h-1.5 w-1.5" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {status === "pending" ? "queued" : status.replaceAll("_", " ")}
    </span>
  );
}
