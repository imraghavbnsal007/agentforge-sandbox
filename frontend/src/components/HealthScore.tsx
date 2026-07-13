import type { HealthPart } from "@/lib/api";

function barColor(score: number): string {
  if (score >= 70) return "bg-gradient-to-r from-emerald-500 to-emerald-400";
  if (score >= 45) return "bg-gradient-to-r from-amber-500 to-amber-400";
  return "bg-gradient-to-r from-red-500 to-red-400";
}

function ringColor(score: number): string {
  if (score >= 70) return "#34d399";
  if (score >= 45) return "#fbbf24";
  return "#f87171";
}

export function HealthScore({
  overall,
  breakdown,
}: {
  overall: number;
  breakdown: Record<string, HealthPart>;
}) {
  return (
    <div className="flex flex-wrap items-start gap-8 px-5 py-5">
      <div
        className="relative grid h-28 w-28 shrink-0 place-items-center rounded-full"
        style={{
          background: `conic-gradient(${ringColor(overall)} ${overall * 3.6}deg, rgba(255,255,255,0.07) 0deg)`,
        }}
        role="img"
        aria-label={`Overall health score ${overall} out of 100`}
      >
        <div className="grid h-[5.5rem] w-[5.5rem] place-items-center rounded-full bg-surface-1">
          <div className="text-center">
            <span className="block text-3xl font-bold tracking-tight text-ink">
              {overall}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-ink-dim">
              / 100
            </span>
          </div>
        </div>
      </div>
      <dl className="min-w-64 flex-1 space-y-3">
        {Object.entries(breakdown).map(([name, part]) => (
          <div key={name}>
            <div className="flex items-center justify-between text-xs">
              <dt className="font-medium capitalize text-ink-mid">{name}</dt>
              <dd className="tabular-nums text-ink-dim">{part.score}</dd>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
              <div
                className={`h-full rounded-full ${barColor(part.score)}`}
                style={{ width: `${part.score}%` }}
              />
            </div>
            <p className="mt-1 text-[11px] leading-4 text-ink-dim">
              {part.reason}
            </p>
          </div>
        ))}
      </dl>
    </div>
  );
}
