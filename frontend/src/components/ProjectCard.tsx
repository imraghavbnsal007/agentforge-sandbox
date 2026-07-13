"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { AnalysisStatusBadge } from "@/components/AnalysisStatusBadge";
import { IconBranch } from "@/components/ui/Icons";
import type { Project } from "@/lib/api";
import { timeAgo } from "@/lib/format";

function healthColor(score: number): string {
  if (score >= 70) return "text-emerald-300";
  if (score >= 45) return "text-amber-300";
  return "text-red-300";
}

function healthRing(score: number): string {
  if (score >= 70) return "#34d399";
  if (score >= 45) return "#fbbf24";
  return "#f87171";
}

/** Compact conic-gradient health dial (0–100). */
function HealthDial({ score }: { score: number }) {
  return (
    <div
      className="relative grid h-12 w-12 shrink-0 place-items-center rounded-full"
      style={{
        background: `conic-gradient(${healthRing(score)} ${score * 3.6}deg, rgba(255,255,255,0.08) 0deg)`,
      }}
      role="img"
      aria-label={`Health score ${score} out of 100`}
    >
      <div className="grid h-9 w-9 place-items-center rounded-full bg-surface-1">
        <span className={`text-xs font-bold ${healthColor(score)}`}>{score}</span>
      </div>
    </div>
  );
}

export function ProjectCard({
  project,
  openTasks,
  index = 0,
}: {
  project: Project;
  openTasks: number;
  index?: number;
}) {
  const repo =
    project.github_owner && project.github_repo
      ? `${project.github_owner}/${project.github_repo}`
      : null;

  return (
    <motion.article
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: Math.min(index * 0.05, 0.4), ease: "easeOut" }}
      className="card card-hover relative flex flex-col gap-4 p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/projects/${project.id}`}
            className="text-[15px] font-semibold leading-snug text-ink outline-none after:absolute after:inset-0 after:content-[''] hover:text-white"
          >
            {project.name}
          </Link>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-dim">
            <IconBranch className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              {repo ? `${repo} · ${project.default_branch}` : "sample repo (local)"}
            </span>
          </p>
        </div>
        {project.health_score != null ? (
          <HealthDial score={project.health_score} />
        ) : (
          <AnalysisStatusBadge status={project.analysis_status} />
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-ink-dim">Language</dt>
          <dd className="mt-0.5 font-medium text-ink-mid">
            {project.primary_language ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-dim">Framework</dt>
          <dd className="mt-0.5 truncate font-medium text-ink-mid">
            {project.framework ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-dim">Open tasks</dt>
          <dd className="mt-0.5 font-medium text-ink-mid">{openTasks}</dd>
        </div>
        <div>
          <dt className="text-ink-dim">Last analysis</dt>
          <dd className="mt-0.5 font-medium text-ink-mid">
            {project.last_analyzed_at ? timeAgo(project.last_analyzed_at) : "never"}
          </dd>
        </div>
        <div className="col-span-2 sm:col-span-1">
          <dt className="text-ink-dim">Status</dt>
          <dd className="mt-1">
            {project.health_score != null ? (
              <AnalysisStatusBadge status={project.analysis_status} />
            ) : (
              <span className="font-medium text-ink-mid">
                {project.analysis_status ?? "not analyzed"}
              </span>
            )}
          </dd>
        </div>
      </dl>
    </motion.article>
  );
}
