import type { AnalysisStatus } from "@/lib/api";

const STYLES: Record<AnalysisStatus, string> = {
  pending: "bg-slate-100 text-slate-600",
  running: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

export function AnalysisStatusBadge({
  status,
  warning = false,
}: {
  status: AnalysisStatus | null;
  warning?: boolean;
}) {
  if (!status) {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-400">
        not analyzed
      </span>
    );
  }
  if (status === "completed" && warning) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800"
        title="Repository facts were analyzed successfully, but AI enrichment could not be parsed."
      >
        analyzed (partial)
      </span>
    );
  }
  const active = status === "pending" || status === "running";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}
    >
      {active && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {status === "completed" ? "analyzed" : status}
    </span>
  );
}
