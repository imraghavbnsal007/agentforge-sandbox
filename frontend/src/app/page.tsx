import Link from "next/link";
import { AutoRefresh } from "@/components/AutoRefresh";
import { ModeBadge } from "@/components/ModeBadge";
import { StatusBadge } from "@/components/StatusBadge";
import {
  getConfig,
  getProjects,
  getTasks,
  type AppConfig,
  type Project,
  type Task,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  let tasks: Task[];
  let projects: Project[];
  let config: AppConfig;
  try {
    [tasks, projects, config] = await Promise.all([
      getTasks(),
      getProjects(),
      getConfig(),
    ]);
  } catch {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-red-700">
        <p className="font-medium">Backend unreachable</p>
        <p className="mt-1 text-sm">
          Could not load tasks. Is the API running? Try{" "}
          <code className="rounded bg-red-100 px-1">docker compose up</code>{" "}
          and refresh.
        </p>
      </div>
    );
  }

  const projectNames = new Map(projects.map((p) => [p.id, p.name]));

  return (
    <div>
      <AutoRefresh />
      <div className="mb-6 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-semibold tracking-tight">Tasks</h2>
            <ModeBadge
              mode={config.agent_mode}
              model={config.agent_mode === "llm" ? config.anthropic_model : undefined}
            />
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Feature requests handled by the agent
          </p>
          {config.agent_mode === "llm" && !config.api_key_configured && (
            <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
              ⚠ AGENT_MODE=llm but no ANTHROPIC_API_KEY configured — runs will fail.
            </p>
          )}
        </div>
        <Link
          href="/tasks/new"
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          New Task
        </Link>
      </div>

      {tasks.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No tasks yet. Seed some data with{" "}
          <code className="rounded bg-slate-100 px-1">make seed</code>.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Task</th>
                <th className="px-4 py-3">Project</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Mode</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((task) => (
                <tr key={task.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link href={`/tasks/${task.id}`} className="group block">
                      <p className="font-medium text-slate-900 group-hover:underline">
                        {task.title}
                      </p>
                      <p className="mt-0.5 line-clamp-1 max-w-md text-xs text-slate-500">
                        {task.request}
                      </p>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {projectNames.get(task.project_id) ?? `#${task.project_id}`}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={task.status} />
                  </td>
                  <td className="px-4 py-3">
                    {task.latest_run_mode ? (
                      <ModeBadge mode={task.latest_run_mode} />
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {new Date(task.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
