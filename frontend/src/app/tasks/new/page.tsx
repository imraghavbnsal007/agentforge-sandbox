import Link from "next/link";
import { NewTaskForm } from "@/components/NewTaskForm";
import { getLLMOptions, getProjects } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function NewTaskPage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string; title?: string; request?: string }>;
}) {
  const params = await searchParams;
  const [projects, options] = await Promise.all([getProjects(), getLLMOptions()]);

  return (
    <div className="mx-auto max-w-2xl">
      <Link
        href="/"
        className="text-sm text-ink-dim transition-colors hover:text-ink-mid"
      >
        ← Back to dashboard
      </Link>
      <h2 className="mt-3 text-2xl font-semibold tracking-tight text-ink">
        New Task
      </h2>
      <p className="mt-1 mb-6 text-sm text-ink-dim">
        Describe a feature request. The agent will plan it, edit the repo, run
        the tests, and write a PR-style summary.
      </p>
      {projects.length === 0 ? (
        <div className="card border-dashed p-8 text-center text-sm text-ink-dim">
          No projects yet — run{" "}
          <code className="rounded bg-surface-3 px-1.5 py-0.5 text-xs">make seed</code>{" "}
          first.
        </div>
      ) : (
        <div className="card p-6">
          <NewTaskForm
            projects={projects}
            options={options}
            defaultProjectId={params.project ? Number(params.project) : undefined}
            defaultTitle={params.title}
            defaultRequest={params.request}
          />
        </div>
      )}
    </div>
  );
}
