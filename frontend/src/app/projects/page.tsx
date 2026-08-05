import { AutoRefresh } from "@/components/AutoRefresh";
import { InstallNotice } from "@/components/InstallNotice";
import { ProjectCard } from "@/components/ProjectCard";
import { RegisterRepoForm } from "@/components/RegisterRepoForm";
import { RepoPicker } from "@/components/RepoPicker";
import { getConfig, getProjects, getRepositories, getTasks, type Task } from "@/lib/api";
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

export default async function ProjectsPage({
  searchParams,
}: {
  // Set by the GitHub App install round trip when it ends in something the
  // user needs to know about.
  searchParams: Promise<{ install_error?: string; install_pending?: string }>;
}) {
  const [params, projects, tasks, auth, config] = await Promise.all([
    searchParams,
    getProjects(),
    getTasks().catch((): Task[] => []),
    getAuthStatus(),
    getConfig().catch(() => null),
  ]);
  const showcase = config?.showcase_mode ?? false;
  const noticeCode = params.install_pending ? "pending" : params.install_error;
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

      <InstallNotice code={noticeCode} />

      {showcase ? (
        <div className="card border-indigo-400/25 bg-indigo-500/[0.06] p-5 text-sm text-indigo-200">
          <p className="font-medium">Repository registration is disabled in demo mode.</p>
          <p className="mt-1.5 text-xs leading-relaxed text-indigo-200/75">
            Running normally, this is where you connect the GitHub App and pick
            which of your repositories AgentForge may read and open pull
            requests against. The project below is the bundled sample.
          </p>
        </div>
      ) : githubAppMode ? (
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
