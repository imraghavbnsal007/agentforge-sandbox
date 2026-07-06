import Link from "next/link";
import { NewTaskForm } from "@/components/NewTaskForm";
import { getProjects } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function NewTaskPage() {
  const projects = await getProjects();

  return (
    <div className="mx-auto max-w-2xl">
      <Link href="/" className="text-sm text-slate-500 hover:text-slate-700">
        ← Back to dashboard
      </Link>
      <h2 className="mt-3 text-2xl font-semibold tracking-tight">New Task</h2>
      <p className="mt-1 mb-6 text-sm text-slate-500">
        Describe a feature request. The agent will plan it, edit the sample
        repo, run the tests, and write a PR-style summary.
      </p>
      {projects.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
          No projects yet — run <code className="rounded bg-slate-100 px-1">make seed</code>{" "}
          first.
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-6">
          <NewTaskForm projects={projects} />
        </div>
      )}
    </div>
  );
}
