import Link from "next/link";
import { AutoRefresh } from "@/components/AutoRefresh";
import { ModeBadge } from "@/components/ModeBadge";
import { TaskBoard } from "@/components/TaskBoard";
import { buttonClasses } from "@/components/ui/Button";
import { IconPlus } from "@/components/ui/Icons";
import {
  getConfig,
  getLLMOptions,
  getProjects,
  getTasks,
  type AppConfig,
  type LLMOptions,
  type Project,
  type Task,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  let tasks: Task[];
  let projects: Project[];
  let config: AppConfig;
  let options: LLMOptions;
  try {
    [tasks, projects, config, options] = await Promise.all([
      getTasks(),
      getProjects(),
      getConfig(),
      getLLMOptions(),
    ]);
  } catch {
    return (
      <div className="card border-red-500/30 bg-red-500/5 p-6 text-red-300">
        <p className="font-medium">Backend unreachable</p>
        <p className="mt-1 text-sm text-red-300/80">
          Could not load tasks. Is the API running? Try{" "}
          <code className="rounded bg-red-500/10 px-1.5 py-0.5">docker compose up</code>{" "}
          and refresh.
        </p>
      </div>
    );
  }
  const showcase = config.showcase_mode;

  return (
    <div className="space-y-6">
      <AutoRefresh />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-semibold tracking-tight text-ink">Tasks</h2>
            <ModeBadge
              mode={config.agent_mode}
              model={config.agent_mode === "llm" ? config.anthropic_model : undefined}
            />
          </div>
          <p className="mt-1 text-sm text-ink-dim">
            Feature requests handled by the agent
          </p>
          {config.agent_mode === "llm" && !config.api_key_configured && (
            <p className="mt-2 rounded-lg bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300 ring-1 ring-inset ring-amber-400/25">
              ⚠ AGENT_MODE=llm but no ANTHROPIC_API_KEY configured — runs will fail.
            </p>
          )}
        </div>
        <Link href="/tasks/new" className={buttonClasses("primary")}>
          <IconPlus className="h-4 w-4" />
          New Task
        </Link>
      </div>

      {tasks.length === 0 ? (
        <div className="card border-dashed p-12 text-center text-ink-dim">
          <p className="text-sm">
            No tasks yet. Seed some data with{" "}
            <code className="rounded bg-surface-3 px-1.5 py-0.5 text-xs">make seed</code>{" "}
            or create your first task.
          </p>
          <Link
            href="/tasks/new"
            className={`${buttonClasses("secondary", "sm")} mt-4`}
          >
            Create a task
          </Link>
        </div>
      ) : (
        <TaskBoard
          tasks={tasks}
          projects={projects}
          profiles={options.profiles}
          canDelete={!showcase}
        />
      )}
    </div>
  );
}
