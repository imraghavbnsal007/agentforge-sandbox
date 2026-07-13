import { getUsage, type UsageBucket } from "@/lib/api";

export const dynamic = "force-dynamic";

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="card p-4">
      <p className="text-xs uppercase tracking-wide text-ink-dim">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-ink">
        {value}
      </p>
    </div>
  );
}

function BucketTable({ title, rows }: { title: string; rows: UsageBucket[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="card overflow-hidden">
      <h3 className="border-b border-line bg-surface-2/60 px-5 py-3 text-xs font-semibold uppercase tracking-wider text-ink-dim">
        {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-ink-dim">
            <tr>
              <th className="px-5 py-2 font-medium">Key</th>
              <th className="px-4 py-2 text-right font-medium">Requests</th>
              <th className="px-4 py-2 text-right font-medium">Tokens in</th>
              <th className="px-4 py-2 text-right font-medium">Tokens out</th>
              <th className="px-4 py-2 text-right font-medium">Cost</th>
              <th className="px-4 py-2 text-right font-medium">Avg latency</th>
              <th className="px-5 py-2 text-right font-medium">Success</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((row) => (
              <tr key={row.key} className="transition-colors hover:bg-surface-2/60">
                <td className="px-5 py-2 font-medium text-ink">{row.key}</td>
                <td className="px-4 py-2 text-right tabular-nums text-ink-mid">
                  {row.requests}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-ink-mid">
                  {row.tokens_in.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-ink-mid">
                  {row.tokens_out.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-ink-mid">
                  ${row.cost_usd.toFixed(4)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-ink-mid">
                  {row.avg_latency_ms} ms
                </td>
                <td
                  className={`px-5 py-2 text-right tabular-nums ${
                    row.success_rate < 1 ? "text-amber-300" : "text-ink-mid"
                  }`}
                >
                  {Math.round(row.success_rate * 100)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default async function UsagePage() {
  const report = await getUsage();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-ink">Usage</h2>
        <p className="mt-1 text-sm text-ink-dim">
          LLM requests, tokens, cost, and reliability across providers
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <StatCard label="Total requests" value={String(report.total_requests)} />
        <StatCard
          label="Tokens used"
          value={(report.total_tokens_in + report.total_tokens_out).toLocaleString()}
        />
        <StatCard label="Total cost" value={`$${report.total_cost_usd.toFixed(4)}`} />
        <StatCard label="Avg latency" value={`${report.avg_latency_ms} ms`} />
        <StatCard
          label="Success rate"
          value={`${Math.round(report.success_rate * 100)}%`}
        />
      </div>

      {report.total_requests === 0 ? (
        <div className="card border-dashed p-12 text-center text-sm text-ink-dim">
          No LLM calls recorded yet — run a task in llm mode or analyze a repository.
        </div>
      ) : (
        <>
          <BucketTable title="Cost per provider" rows={report.by_provider} />
          <BucketTable title="Cost per model" rows={report.by_model} />
          <BucketTable title="Cost per project / repository" rows={report.by_project} />
        </>
      )}
    </div>
  );
}
