"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LLMPicker, type LLMSelection } from "@/components/LLMPicker";
import { createTask, type LLMOptions, type Project } from "@/lib/api";

function selectionForProject(
  project: Project | undefined,
  options: LLMOptions,
): LLMSelection {
  if (project?.preferred_provider && project?.preferred_model) {
    return {
      profile: "custom",
      provider: project.preferred_provider,
      model: project.preferred_model,
    };
  }
  const firstConfigured = options.providers.find(
    (p) => p.implemented && p.configured,
  );
  return {
    profile: project?.preferred_execution_profile ?? "balanced",
    provider: firstConfigured?.name ?? options.default_provider,
    model: firstConfigured?.models[0] ?? options.default_model,
  };
}

export function NewTaskForm({
  projects,
  options,
  defaultProjectId,
  defaultTitle,
  defaultRequest,
}: {
  projects: Project[];
  options: LLMOptions;
  defaultProjectId?: number;
  defaultTitle?: string;
  defaultRequest?: string;
}) {
  const router = useRouter();
  const validDefault = projects.some((p) => p.id === defaultProjectId)
    ? defaultProjectId
    : undefined;
  const initialProject = projects.find(
    (p) => p.id === (validDefault ?? projects[0]?.id),
  );
  const [projectId, setProjectId] = useState(validDefault ?? projects[0]?.id ?? 0);
  const [title, setTitle] = useState(defaultTitle ?? "");
  const [request, setRequest] = useState(defaultRequest ?? "");
  const [llm, setLlm] = useState<LLMSelection>(() =>
    selectionForProject(initialProject, options),
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function onProjectChange(id: number) {
    setProjectId(id);
    setLlm(selectionForProject(projects.find((p) => p.id === id), options));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const task = await createTask({
        project_id: projectId,
        title,
        request,
        ...(llm.profile === "custom"
          ? { llm_provider: llm.provider, llm_model: llm.model }
          : { execution_profile: llm.profile }),
      });
      router.push(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          Project
        </label>
        <select
          value={projectId}
          onChange={(e) => onProjectChange(Number(e.target.value))}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          Title
        </label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={200}
          placeholder="Add a divide function"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          Feature request
        </label>
        <textarea
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          required
          rows={6}
          placeholder="Describe the feature you want the agent to implement in the sample repo…"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
      </div>

      <LLMPicker options={options} value={llm} onChange={setLlm} />

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting || projects.length === 0}
        className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Run the agent"}
      </button>
    </form>
  );
}
