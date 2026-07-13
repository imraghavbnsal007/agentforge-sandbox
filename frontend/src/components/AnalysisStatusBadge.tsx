import type { AnalysisStatus } from "@/lib/api";

const STYLES: Record<AnalysisStatus, string> = {
  pending: "bg-orange-500/12 text-orange-300 ring-orange-400/25",
  running: "bg-blue-500/12 text-blue-300 ring-blue-400/25",
  completed: "bg-emerald-500/12 text-emerald-300 ring-emerald-400/25",
  failed: "bg-red-500/12 text-red-300 ring-red-400/25",
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
      <span className="inline-flex items-center rounded-full bg-slate-500/12 px-2.5 py-0.5 text-xs font-medium text-slate-400 ring-1 ring-inset ring-slate-400/20">
        not analyzed
      </span>
    );
  }
  if (status === "completed" && warning) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/12 px-2.5 py-0.5 text-xs font-medium text-amber-300 ring-1 ring-inset ring-amber-400/25"
        title="Repository facts were analyzed successfully, but AI enrichment could not be parsed."
      >
        analyzed (partial)
      </span>
    );
  }
  const active = status === "pending" || status === "running";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status]}`}
    >
      {active && (
        <span className="relative flex h-1.5 w-1.5" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {status === "completed" ? "analyzed" : status}
    </span>
  );
}
