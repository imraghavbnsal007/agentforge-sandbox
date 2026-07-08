import { getUsage, type UsageBucket } from "@/lib/api";

export const dynamic = "force-dynamic";

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function BucketTable({ title, rows }: { title: string; rows: UsageBucket[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <h3 className="border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-4 py-2">Key</th>
            <th className="px-4 py-2 text-right">Requests</th>
            <th className="px-4 py-2 text-right">Tokens in</th>
            <th className="px-4 py-2 text-right">Tokens out</th>
            <th className="px-4 py-2 text-right">Cost</th>
            <th className="px-4 py-2 text-right">Avg latency</th>
            <th className="px-4 py-2 text-right">Success</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="px-4 py-2 font-medium text-slate-800">{row.key}</td>
              <td className="px-4 py-2 text-right text-slate-600">{row.requests}</td>
              <td className="px-4 py-2 text-right text-slate-600">
                {row.tokens_in.toLocaleString()}
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                {row.tokens_out.toLocaleString()}
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                ${row.cost_usd.toFixed(4)}
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                {row.avg_latency_ms} ms
              </td>
              <td className="px-4 py-2 text-right text-slate-600">
                {Math.round(row.success_rate * 100)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default async function UsagePage() {
  const report = await getUsage();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Usage</h2>
        <p className="mt-1 text-sm text-slate-500">
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
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
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
