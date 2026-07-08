import type { HealthPart } from "@/lib/api";

function color(score: number): string {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 45) return "bg-amber-500";
  return "bg-red-500";
}

export function HealthScore({
  overall,
  breakdown,
}: {
  overall: number;
  breakdown: Record<string, HealthPart>;
}) {
  return (
    <div className="flex flex-wrap items-start gap-6 px-4 py-4">
      <div className="flex h-24 w-24 shrink-0 flex-col items-center justify-center rounded-full border-4 border-slate-200">
        <span className="text-3xl font-bold text-slate-900">{overall}</span>
        <span className="text-[10px] uppercase tracking-wide text-slate-400">
          / 100
        </span>
      </div>
      <dl className="min-w-64 flex-1 space-y-2.5">
        {Object.entries(breakdown).map(([name, part]) => (
          <div key={name}>
            <div className="flex items-center justify-between text-xs">
              <dt className="font-medium capitalize text-slate-700">{name}</dt>
              <dd className="text-slate-500">{part.score}</dd>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full ${color(part.score)}`}
                style={{ width: `${part.score}%` }}
              />
            </div>
            <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
              {part.reason}
            </p>
          </div>
        ))}
      </dl>
    </div>
  );
}
