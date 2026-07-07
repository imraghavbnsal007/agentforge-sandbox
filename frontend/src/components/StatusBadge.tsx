import type { TaskStatus } from "@/lib/api";

const STYLES: Record<TaskStatus, string> = {
  pending: "bg-slate-100 text-slate-600",
  planning: "bg-blue-100 text-blue-700",
  coding: "bg-violet-100 text-violet-700",
  testing: "bg-amber-100 text-amber-700",
  ready_for_review: "bg-indigo-100 text-indigo-700",
  publishing: "bg-cyan-100 text-cyan-700",
  rejected: "bg-slate-200 text-slate-500",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

const ACTIVE: TaskStatus[] = ["planning", "coding", "testing", "publishing"];

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}
    >
      {ACTIVE.includes(status) && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {status.replaceAll("_", " ")}
    </span>
  );
}
