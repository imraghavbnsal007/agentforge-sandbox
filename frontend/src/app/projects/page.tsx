import { AutoRefresh } from "@/components/AutoRefresh";
import { ProjectCard } from "@/components/ProjectCard";
import { RegisterRepoForm } from "@/components/RegisterRepoForm";
import { RepoPicker } from "@/components/RepoPicker";
import { getProjects, getRepositories, getTasks, type Task } from "@/lib/api";
import { EMPTY_REPOSITORY_LIST, type RepositoryList } from "@/lib/repositories";
import { getAuthStatus } from "@/lib/session";

export const dynamic = "force-dynamic";

/** Statuses that count as "open" on a project card. */
const OPEN_STATUSES = new Set([
  "pending",
  "planning",
  "coding",
  "testing",
  "ready_for_review",
  "publishing",
]);

export default async function ProjectsPage() {
  const [projects, tasks, auth] = await Promise.all([
    getProjects(),
    getTasks().catch((): Task[] => []),
    getAuthStatus(),
  ]);
  const githubAppMode = auth.auth_mode === "github_app";
  // Discovery only exists in github_app mode; a failure here must not take
  // the whole page down, so it degrades to the install prompt.
  const repositories: RepositoryList = githubAppMode
    ? await getRepositories().catch(() => EMPTY_REPOSITORY_LIST)
    : EMPTY_REPOSITORY_LIST;
  const anyActive = projects.some(
    (p) => p.analysis_status === "pending" || p.analysis_status === "running",
  );

  const openTaskCounts = new Map<number, number>();
  for (const task of tasks) {
    if (OPEN_STATUSES.has(task.status)) {
      openTaskCounts.set(task.project_id, (openTaskCounts.get(task.project_id) ?? 0) + 1);
    }
  }

  return (
    <div className="space-y-6">
      {anyActive && <AutoRefresh intervalMs={3000} />}
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-ink">Projects</h2>
        <p className="mt-1 text-sm text-ink-dim">
          Registered repositories and what AgentForge knows about them
        </p>
      </div>

      {githubAppMode ? (
        <RepoPicker initial={repositories} />
      ) : (
        <RegisterRepoForm />
      )}

      {projects.length === 0 ? (
        <div className="card border-dashed p-12 text-center text-sm text-ink-dim">
          {githubAppMode
            ? "No projects yet — register one of your granted repositories above."
            : "No projects yet — register a repository above."}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {projects.map((project, i) => (
            <ProjectCard
              key={project.id}
              project={project}
              openTasks={openTaskCounts.get(project.id) ?? 0}
              index={i}
            />
          ))}
        </div>
      )}
    </div>
  );
}
