"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { TaskCard } from "@/components/TaskCard";
import { IconSearch } from "@/components/ui/Icons";
import type { Project, ProfileInfo, Task, TaskStatus } from "@/lib/api";

type FilterKey = "all" | "running" | "queued" | "review" | "completed" | "failed" | "cancelled";

const FILTERS: { key: FilterKey; label: string; statuses: TaskStatus[] | null }[] = [
  { key: "all", label: "All", statuses: null },
  { key: "running", label: "Running", statuses: ["planning", "coding", "testing", "publishing"] },
  { key: "queued", label: "Queued", statuses: ["pending"] },
  { key: "review", label: "Review", statuses: ["ready_for_review"] },
  { key: "completed", label: "Completed", statuses: ["completed"] },
  { key: "failed", label: "Failed", statuses: ["failed"] },
  { key: "cancelled", label: "Cancelled", statuses: ["rejected"] },
];

export function TaskBoard({
  tasks,
  projects,
  profiles,
}: {
  tasks: Task[];
  projects: Project[];
  profiles: ProfileInfo[];
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const searchRef = useRef<HTMLInputElement>(null);

  // "/" focuses search from anywhere on the page.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      e.preventDefault();
      searchRef.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const projectById = useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects]);
  const costByProfile = useMemo(
    () => new Map(profiles.map((p) => [p.name, p.estimated_cost_usd])),
    [profiles],
  );

  const counts = useMemo(() => {
    const map = new Map<FilterKey, number>();
    for (const f of FILTERS) {
      map.set(
        f.key,
        f.statuses === null
          ? tasks.length
          : tasks.filter((t) => f.statuses!.includes(t.status)).length,
      );
    }
    return map;
  }, [tasks]);

  const visible = useMemo(() => {
    const active = FILTERS.find((f) => f.key === filter);
    const q = query.trim().toLowerCase();
    return tasks.filter((task) => {
      if (active?.statuses && !active.statuses.includes(task.status)) return false;
      if (!q) return true;
      const project = projectById.get(task.project_id);
      return (
        task.title.toLowerCase().includes(q) ||
        task.request.toLowerCase().includes(q) ||
        (project?.name.toLowerCase().includes(q) ?? false) ||
        (task.llm_model?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [tasks, filter, query, projectById]);

  return (
    <div className="space-y-4">
      {/* Search + status filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative sm:max-w-xs sm:flex-1">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-dim" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            type="search"
            placeholder="Search tasks…  ( / )"
            aria-label="Search tasks"
            className="field pl-9"
          />
        </div>
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="group"
          aria-label="Filter tasks by status"
        >
          {FILTERS.map((f) => {
            const count = counts.get(f.key) ?? 0;
            if (f.key !== "all" && count === 0) return null;
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                aria-pressed={active}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors duration-150 ${
                  active
                    ? "bg-accent-soft text-ink ring-1 ring-inset ring-indigo-400/40"
                    : "text-ink-dim hover:bg-surface-2 hover:text-ink-mid"
                }`}
              >
                {f.label}
                <span className={`ml-1.5 ${active ? "text-accent" : "text-ink-dim/70"}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="card p-12 text-center text-sm text-ink-dim">
          {tasks.length === 0
            ? "No tasks yet — create one to put the agent to work."
            : "No tasks match the current search or filter."}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {visible.map((task, i) => {
            const project = projectById.get(task.project_id);
            const repo =
              project?.github_owner && project?.github_repo
                ? `${project.github_owner}/${project.github_repo}`
                : null;
            return (
              <TaskCard
                key={task.id}
                task={task}
                projectName={project?.name ?? `Project #${task.project_id}`}
                repo={repo}
                estimatedCost={
                  task.execution_profile
                    ? (costByProfile.get(task.execution_profile) ?? null)
                    : null
                }
                index={i}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
