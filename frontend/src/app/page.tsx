import { AutoRefresh } from "@/components/AutoRefresh";
import { StatusBadge } from "@/components/StatusBadge";
import { getProjects, getTasks, type Project, type Task } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  let tasks: Task[];
  let projects: Project[];
  try {
    [tasks, projects] = await Promise.all([getTasks(), getProjects()]);
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
          <h2 className="text-2xl font-semibold tracking-tight">Tasks</h2>
          <p className="mt-1 text-sm text-slate-500">
            Feature requests handled by the agent
          </p>
        </div>
        <span className="cursor-not-allowed rounded-lg bg-slate-200 px-4 py-2 text-sm font-medium text-slate-400">
          New Task (Phase 2)
        </span>
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
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tasks.map((task) => (
                <tr key={task.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-900">{task.title}</p>
                    <p className="mt-0.5 line-clamp-1 max-w-md text-xs text-slate-500">
                      {task.request}
                    </p>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {projectNames.get(task.project_id) ?? `#${task.project_id}`}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={task.status} />
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
