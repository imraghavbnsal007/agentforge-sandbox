"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { InstallAppCard } from "@/components/InstallAppCard";
import { Button, Spinner } from "@/components/ui/Button";
import { IconBranch, IconRetry, IconSearch } from "@/components/ui/Icons";
import { refreshRepositories, registerRepository } from "@/lib/api";
import {
  DEFAULT_FILTERS,
  accountsOf,
  blockedReason,
  canRegister,
  filterRepositories,
  groupByAccount,
  type RepoFilters,
  type VisibilityFilter,
} from "@/lib/repoFilters";
import type { Repository, RepositoryList } from "@/lib/repositories";

function VisibilityBadge({ isPrivate }: { isPrivate: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
        isPrivate
          ? "bg-amber-500/12 text-amber-300 ring-amber-400/25"
          : "bg-slate-500/12 text-slate-300 ring-slate-400/20"
      }`}
    >
      {isPrivate ? "Private" : "Public"}
    </span>
  );
}

function RepoRow({
  repository,
  onRegistered,
}: {
  repository: Repository;
  onRegistered: (repositoryId: number, projectId: number) => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blocked = blockedReason(repository);
  const registerable = canRegister(repository);

  async function onRegister() {
    setBusy(true);
    setError(null);
    try {
      // Registration is by GitHub's numeric repository id — never a URL — so
      // the backend can check it against this user's installation grants.
      const project = await registerRepository(repository.github_repository_id);
      onRegistered(repository.github_repository_id, project.id);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line px-4 py-3 first:border-t-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {repository.full_name}
          </span>
          <VisibilityBadge isPrivate={repository.private} />
          {repository.archived && (
            <span className="inline-flex items-center rounded-full bg-red-500/12 px-2 py-0.5 text-[11px] font-medium text-red-300 ring-1 ring-inset ring-red-400/25">
              Archived
            </span>
          )}
        </div>
        <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-dim">
          <IconBranch className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{repository.default_branch}</span>
        </p>
        {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
      </div>

      {repository.is_registered && repository.project_id ? (
        <Link
          href={`/projects/${repository.project_id}`}
          className="rounded-lg bg-emerald-500/12 px-3 py-1.5 text-xs font-medium text-emerald-300 ring-1 ring-inset ring-emerald-400/25 transition-colors hover:bg-emerald-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60"
        >
          Registered — open
        </Link>
      ) : (
        <Button
          size="sm"
          onClick={onRegister}
          disabled={!registerable || busy}
          title={blocked ?? `Register ${repository.full_name}`}
        >
          {busy ? <Spinner className="h-3.5 w-3.5" /> : "Register"}
        </Button>
      )}

      {blocked && !repository.is_registered && (
        <p className="w-full text-xs text-ink-dim">{blocked}</p>
      )}
    </li>
  );
}

export function RepoPicker({ initial }: { initial: RepositoryList }) {
  const router = useRouter();
  const [data, setData] = useState<RepositoryList>(initial);
  const [filters, setFilters] = useState<RepoFilters>(DEFAULT_FILTERS);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const accounts = useMemo(
    () => accountsOf(data.repositories),
    [data.repositories],
  );
  const visible = useMemo(
    () => filterRepositories(data.repositories, filters),
    [data.repositories, filters],
  );
  const groups = useMemo(() => groupByAccount(visible), [visible]);

  function patch(next: Partial<RepoFilters>) {
    setFilters((prev) => ({ ...prev, ...next }));
  }

  function markRegistered(repositoryId: number, projectId: number) {
    // Optimistic: reflect the new state without waiting for a refetch.
    setData((prev) => ({
      ...prev,
      repositories: prev.repositories.map((r) =>
        r.github_repository_id === repositoryId
          ? { ...r, is_registered: true, project_id: projectId }
          : r,
      ),
    }));
  }

  async function onRefresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      setData(await refreshRepositories());
      router.refresh();
    } catch (err) {
      setRefreshError(
        err instanceof Error ? err.message : "Could not refresh repositories",
      );
    } finally {
      setRefreshing(false);
    }
  }

  if (!data.has_installations) {
    return (
      <InstallAppCard
        installUrl={data.install_url}
        appConfigured={data.app_configured}
      />
    );
  }

  return (
    <section className="space-y-4" aria-labelledby="repo-picker-heading">
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <h3
            id="repo-picker-heading"
            className="text-[13px] font-semibold uppercase tracking-wide text-ink-dim"
          >
            Available repositories
          </h3>
          <span className="text-xs text-ink-dim">
            {visible.length} of {data.repositories.length}
          </span>
          <div className="ml-auto">
            <Button
              variant="secondary"
              size="sm"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <IconRetry className="h-3.5 w-3.5" />
              )}
              Refresh
            </Button>
          </div>
        </div>

        <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-[1fr_auto_auto]">
          <div className="relative">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-dim" />
            <input
              ref={searchRef}
              type="search"
              value={filters.query}
              onChange={(e) => patch({ query: e.target.value })}
              placeholder="Search repositories…"
              aria-label="Search repositories"
              className="field w-full pl-9"
            />
          </div>

          <div>
            <label htmlFor="repo-account" className="sr-only">
              Filter by account
            </label>
            <select
              id="repo-account"
              value={filters.account}
              onChange={(e) => patch({ account: e.target.value })}
              className="field w-full sm:w-44"
            >
              <option value="all">All accounts</option>
              {accounts.map((account) => (
                <option key={account} value={account}>
                  {account}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="repo-visibility" className="sr-only">
              Filter by visibility
            </label>
            <select
              id="repo-visibility"
              value={filters.visibility}
              onChange={(e) =>
                patch({ visibility: e.target.value as VisibilityFilter })
              }
              className="field w-full sm:w-36"
            >
              <option value="all">Public &amp; private</option>
              <option value="public">Public only</option>
              <option value="private">Private only</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-xs text-ink-mid sm:col-span-3">
            <input
              type="checkbox"
              checked={filters.hideRegistered}
              onChange={(e) => patch({ hideRegistered: e.target.checked })}
              className="h-3.5 w-3.5 rounded border-line-strong bg-surface-3"
            />
            Hide already registered
          </label>
        </div>

        {refreshError && (
          <p role="alert" className="border-b border-line px-4 py-3 text-xs text-red-400">
            {refreshError}
          </p>
        )}

        {visible.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-ink-dim">
            {data.repositories.length === 0
              ? "The installation does not grant access to any repositories yet."
              : "No repositories match these filters."}
          </p>
        ) : (
          groups.map((group) => (
            <div key={group.account}>
              {accounts.length > 1 && (
                <h4 className="bg-surface-2/60 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-dim">
                  {group.account}
                </h4>
              )}
              <ul>
                {group.repositories.map((repository) => (
                  <RepoRow
                    key={repository.github_repository_id}
                    repository={repository}
                    onRegistered={markRegistered}
                  />
                ))}
              </ul>
            </div>
          ))
        )}
      </div>

      <InstallAppCard
        installUrl={data.install_url}
        appConfigured={data.app_configured}
        manage
      />
    </section>
  );
}
