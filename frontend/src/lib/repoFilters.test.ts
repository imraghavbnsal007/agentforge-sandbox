import { describe, expect, it } from "vitest";

import {
  DEFAULT_FILTERS,
  accountsOf,
  blockedReason,
  canRegister,
  filterRepositories,
  groupByAccount,
} from "@/lib/repoFilters";
import type { Repository } from "@/lib/repositories";

function repo(overrides: Partial<Repository> = {}): Repository {
  const owner = overrides.owner ?? "octocat";
  const name = overrides.name ?? "hello";
  return {
    github_repository_id: 1,
    owner,
    name,
    full_name: `${owner}/${name}`,
    default_branch: "main",
    private: false,
    archived: false,
    disabled: false,
    is_usable: true,
    last_synced_at: null,
    installation_id: 500,
    installation_account: owner,
    installation_active: true,
    is_registered: false,
    project_id: null,
    ...overrides,
  };
}

describe("filterRepositories", () => {
  const repositories = [
    repo({ github_repository_id: 1, owner: "octocat", name: "hello" }),
    repo({ github_repository_id: 2, owner: "octocat", name: "world", private: true }),
    repo({ github_repository_id: 3, owner: "acme", name: "widget" }),
  ];

  it("returns everything with default filters", () => {
    expect(filterRepositories(repositories, DEFAULT_FILTERS)).toHaveLength(3);
  });

  it("matches a bare name fragment", () => {
    const found = filterRepositories(repositories, {
      ...DEFAULT_FILTERS,
      query: "wid",
    });
    expect(found.map((r) => r.full_name)).toEqual(["acme/widget"]);
  });

  it("matches against the owner too", () => {
    const found = filterRepositories(repositories, {
      ...DEFAULT_FILTERS,
      query: "octocat/",
    });
    expect(found).toHaveLength(2);
  });

  it("ignores case and surrounding whitespace", () => {
    const found = filterRepositories(repositories, {
      ...DEFAULT_FILTERS,
      query: "  WIDGET ",
    });
    expect(found.map((r) => r.name)).toEqual(["widget"]);
  });

  it("filters by account", () => {
    const found = filterRepositories(repositories, {
      ...DEFAULT_FILTERS,
      account: "acme",
    });
    expect(found.map((r) => r.full_name)).toEqual(["acme/widget"]);
  });

  it("filters to private only", () => {
    const found = filterRepositories(repositories, {
      ...DEFAULT_FILTERS,
      visibility: "private",
    });
    expect(found.map((r) => r.name)).toEqual(["world"]);
  });

  it("filters to public only", () => {
    const found = filterRepositories(repositories, {
      ...DEFAULT_FILTERS,
      visibility: "public",
    });
    expect(found.map((r) => r.name)).toEqual(["hello", "widget"]);
  });

  it("hides already-registered repositories on request", () => {
    const withRegistered = [
      ...repositories,
      repo({ github_repository_id: 4, name: "done", is_registered: true }),
    ];
    const found = filterRepositories(withRegistered, {
      ...DEFAULT_FILTERS,
      hideRegistered: true,
    });
    expect(found.some((r) => r.is_registered)).toBe(false);
  });

  it("combines filters", () => {
    const found = filterRepositories(repositories, {
      query: "o",
      account: "octocat",
      visibility: "private",
      hideRegistered: false,
    });
    expect(found.map((r) => r.name)).toEqual(["world"]);
  });

  it("returns nothing when no repository matches", () => {
    expect(
      filterRepositories(repositories, { ...DEFAULT_FILTERS, query: "zzz" }),
    ).toEqual([]);
  });
});

describe("accountsOf", () => {
  it("returns distinct accounts, sorted", () => {
    const accounts = accountsOf([
      repo({ owner: "octocat" }),
      repo({ owner: "acme" }),
      repo({ owner: "octocat", name: "other" }),
    ]);
    expect(accounts).toEqual(["acme", "octocat"]);
  });

  it("is empty for no repositories", () => {
    expect(accountsOf([])).toEqual([]);
  });
});

describe("groupByAccount", () => {
  it("groups and sorts by account", () => {
    const groups = groupByAccount([
      repo({ github_repository_id: 1, owner: "octocat" }),
      repo({ github_repository_id: 2, owner: "acme" }),
      repo({ github_repository_id: 3, owner: "octocat", name: "second" }),
    ]);
    expect(groups.map((g) => g.account)).toEqual(["acme", "octocat"]);
    expect(groups[1].repositories).toHaveLength(2);
  });
});

describe("blockedReason", () => {
  it("allows a healthy unregistered repository", () => {
    expect(blockedReason(repo())).toBeNull();
    expect(canRegister(repo())).toBe(true);
  });

  it("blocks an already-registered repository", () => {
    expect(blockedReason(repo({ is_registered: true }))).toBe(
      "Already registered",
    );
  });

  it("blocks when the installation is suspended", () => {
    expect(blockedReason(repo({ installation_active: false }))).toMatch(
      /suspended/,
    );
  });

  it("blocks an archived repository", () => {
    expect(blockedReason(repo({ archived: true }))).toBe("Archived on GitHub");
    expect(canRegister(repo({ archived: true }))).toBe(false);
  });

  it("blocks a disabled repository", () => {
    expect(blockedReason(repo({ disabled: true }))).toBe("Disabled on GitHub");
  });

  it("reports registration before other reasons", () => {
    // A registered repository should read as registered, not as archived.
    expect(blockedReason(repo({ is_registered: true, archived: true }))).toBe(
      "Already registered",
    );
  });
});
