import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RepoPicker } from "@/components/RepoPicker";
import type { Repository, RepositoryList } from "@/lib/repositories";

const refreshMock = vi.fn();
const registerMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  refreshRepositories: (...args: unknown[]) => refreshMock(...args),
  registerRepository: (...args: unknown[]) => registerMock(...args),
}));

afterEach(cleanup);

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

function list(overrides: Partial<RepositoryList> = {}): RepositoryList {
  return {
    app_configured: true,
    install_url: "https://github.com/apps/agentforge-dev/installations/new",
    has_installations: true,
    repositories: [repo()],
    ...overrides,
  };
}

describe("RepoPicker empty states", () => {
  it("prompts to install when there are no installations", () => {
    render(<RepoPicker initial={list({ has_installations: false })} />);
    expect(screen.getByText(/Install AgentForge on GitHub/i)).toBeDefined();
    expect(
      screen.getByRole("link", { name: /Install GitHub App/i }),
    ).toBeDefined();
  });

  it("explains when the App is not configured on the server", () => {
    render(
      <RepoPicker
        initial={list({ has_installations: false, app_configured: false, install_url: null })}
      />,
    );
    expect(screen.getByText(/not configured on this server/i)).toBeDefined();
  });

  it("says so when an installation grants no repositories", () => {
    render(<RepoPicker initial={list({ repositories: [] })} />);
    expect(screen.getByText(/does not grant access to any repositories/i)).toBeDefined();
  });

  it("offers a manage link when installations exist", () => {
    render(<RepoPicker initial={list()} />);
    expect(
      screen.getByRole("link", { name: /Manage GitHub App access/i }),
    ).toBeDefined();
  });
});

describe("RepoPicker listing", () => {
  it("renders repository name, branch and visibility badge", () => {
    render(<RepoPicker initial={list({ repositories: [repo({ private: true })] })} />);
    expect(screen.getByText("octocat/hello")).toBeDefined();
    expect(screen.getByText("main")).toBeDefined();
    expect(screen.getByText("Private")).toBeDefined();
  });

  it("marks a public repository", () => {
    render(<RepoPicker initial={list()} />);
    expect(screen.getByText("Public")).toBeDefined();
  });

  it("shows a link instead of a button once registered", () => {
    render(
      <RepoPicker
        initial={list({
          repositories: [repo({ is_registered: true, project_id: 7 })],
        })}
      />,
    );
    const link = screen.getByRole("link", { name: /Registered — open/i });
    expect(link.getAttribute("href")).toBe("/projects/7");
    expect(screen.queryByRole("button", { name: "Register" })).toBeNull();
  });

  it("disables Register for an archived repository and explains why", () => {
    render(<RepoPicker initial={list({ repositories: [repo({ archived: true })] })} />);
    const button = screen.getByRole("button", { name: "Register" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Archived on GitHub")).toBeDefined();
  });

  it("disables Register when the installation is suspended", () => {
    render(
      <RepoPicker
        initial={list({ repositories: [repo({ installation_active: false })] })}
      />,
    );
    expect(
      (screen.getByRole("button", { name: "Register" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("RepoPicker filtering", () => {
  const many = list({
    repositories: [
      repo({ github_repository_id: 1, owner: "octocat", name: "hello" }),
      repo({ github_repository_id: 2, owner: "octocat", name: "world", private: true }),
      repo({ github_repository_id: 3, owner: "acme", name: "widget" }),
    ],
  });

  it("filters by search text", () => {
    render(<RepoPicker initial={many} />);
    fireEvent.change(screen.getByLabelText(/Search repositories/i), {
      target: { value: "widget" },
    });
    expect(screen.getByText("acme/widget")).toBeDefined();
    expect(screen.queryByText("octocat/hello")).toBeNull();
  });

  it("filters by account", () => {
    render(<RepoPicker initial={many} />);
    fireEvent.change(screen.getByLabelText(/Filter by account/i), {
      target: { value: "acme" },
    });
    expect(screen.getByText("acme/widget")).toBeDefined();
    expect(screen.queryByText("octocat/world")).toBeNull();
  });

  it("filters by visibility", () => {
    render(<RepoPicker initial={many} />);
    fireEvent.change(screen.getByLabelText(/Filter by visibility/i), {
      target: { value: "private" },
    });
    expect(screen.getByText("octocat/world")).toBeDefined();
    expect(screen.queryByText("acme/widget")).toBeNull();
  });

  it("reports when filters match nothing", () => {
    render(<RepoPicker initial={many} />);
    fireEvent.change(screen.getByLabelText(/Search repositories/i), {
      target: { value: "nothing-matches" },
    });
    expect(screen.getByText(/No repositories match these filters/i)).toBeDefined();
  });

  it("shows a visible/total count that tracks filtering", () => {
    render(<RepoPicker initial={many} />);
    expect(screen.getByText("3 of 3")).toBeDefined();
    fireEvent.change(screen.getByLabelText(/Search repositories/i), {
      target: { value: "acme" },
    });
    expect(screen.getByText("1 of 3")).toBeDefined();
  });
});

describe("RepoPicker registration", () => {
  it("registers by repository id, not by URL", async () => {
    registerMock.mockResolvedValueOnce({ id: 42 });
    render(<RepoPicker initial={list({ repositories: [repo({ github_repository_id: 909 })] })} />);

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(registerMock).toHaveBeenCalledWith(909));
  });

  it("reflects the new state without a reload", async () => {
    registerMock.mockResolvedValueOnce({ id: 42 });
    render(<RepoPicker initial={list()} />);

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(screen.getByRole("link", { name: /Registered — open/i })).toBeDefined(),
    );
  });

  it("surfaces a registration failure without losing the row", async () => {
    registerMock.mockRejectedValueOnce(new Error("That repository is not available"));
    render(<RepoPicker initial={list()} />);

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(screen.getByText(/not available/i)).toBeDefined(),
    );
    expect(screen.getByText("octocat/hello")).toBeDefined();
  });
});

describe("RepoPicker refresh", () => {
  it("replaces the list with refreshed data", async () => {
    refreshMock.mockResolvedValueOnce(
      list({ repositories: [repo({ github_repository_id: 2, name: "fresh" })] }),
    );
    render(<RepoPicker initial={list()} />);

    fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));

    await waitFor(() => expect(screen.getByText("octocat/fresh")).toBeDefined());
  });

  it("reports a refresh failure", async () => {
    refreshMock.mockRejectedValueOnce(new Error("GitHub is unreachable"));
    render(<RepoPicker initial={list()} />);

    fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/unreachable/i),
    );
  });
});
