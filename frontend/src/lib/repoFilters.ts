/** Pure filtering and grouping for the repository picker.
 *
 * Kept free of React so the selection rules — which decide what a user can
 * see and register — are testable on their own.
 */

import type { Repository } from "@/lib/repositories";

export type VisibilityFilter = "all" | "public" | "private";

export interface RepoFilters {
  /** Free-text match against the full name. */
  query: string;
  /** Installation account login, or "all". */
  account: string;
  visibility: VisibilityFilter;
  /** Hide repositories already registered as a project. */
  hideRegistered: boolean;
}

export const DEFAULT_FILTERS: RepoFilters = {
  query: "",
  account: "all",
  visibility: "all",
  hideRegistered: false,
};

/** Distinct accounts, sorted, for the account dropdown. */
export function accountsOf(repositories: Repository[]): string[] {
  return [...new Set(repositories.map((r) => r.installation_account))].sort(
    (a, b) => a.localeCompare(b),
  );
}

function matchesQuery(repository: Repository, query: string): boolean {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return true;
  // Match the full name so "owner/re" works as well as bare "re".
  return repository.full_name.toLowerCase().includes(trimmed);
}

export function filterRepositories(
  repositories: Repository[],
  filters: RepoFilters,
): Repository[] {
  return repositories.filter((repository) => {
    if (!matchesQuery(repository, filters.query)) return false;
    if (
      filters.account !== "all" &&
      repository.installation_account !== filters.account
    ) {
      return false;
    }
    if (filters.visibility === "public" && repository.private) return false;
    if (filters.visibility === "private" && !repository.private) return false;
    if (filters.hideRegistered && repository.is_registered) return false;
    return true;
  });
}

/** Repositories grouped by account, for a sectioned list. */
export function groupByAccount(
  repositories: Repository[],
): { account: string; repositories: Repository[] }[] {
  const groups = new Map<string, Repository[]>();
  for (const repository of repositories) {
    const existing = groups.get(repository.installation_account);
    if (existing) existing.push(repository);
    else groups.set(repository.installation_account, [repository]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([account, items]) => ({ account, repositories: items }));
}

/** Why a repository cannot be registered, or null when it can. */
export function blockedReason(repository: Repository): string | null {
  if (repository.is_registered) return "Already registered";
  if (!repository.installation_active) {
    return "The GitHub App installation for this account is suspended";
  }
  if (repository.archived) return "Archived on GitHub";
  if (repository.disabled) return "Disabled on GitHub";
  return null;
}

export function canRegister(repository: Repository): boolean {
  return blockedReason(repository) === null;
}
