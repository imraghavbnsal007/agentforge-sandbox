import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewActions } from "@/components/ReviewActions";

const approveMock = vi.fn();
const rejectMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  approveTask: (...args: unknown[]) => approveMock(...args),
  rejectTask: (...args: unknown[]) => rejectMock(...args),
}));

afterEach(cleanup);

function result(overrides: Record<string, unknown> = {}) {
  return { suite: "pytest", passed: 7, failed: 0, errored: 0, ...overrides };
}

function text() {
  return screen
    .getByRole("button", { name: "Approve & Create PR" })
    .closest("div.card")!.textContent!;
}

// The banner used to say "Tests passed" unconditionally, directly above a
// warning that no test command had been detected. Both were true — nothing
// failed because nothing ran — but together they invited approving an
// unverified diff of 130 files on the strength of a reassurance nobody had
// earned.

describe("what the run actually proved", () => {
  it("does not claim tests passed when none ran", () => {
    render(<ReviewActions taskId={1} tests={[]} />);
    expect(text()).not.toMatch(/passed/i);
    expect(text()).toMatch(/not verified by tests/i);
  });

  it("says so plainly when tests did pass", () => {
    render(<ReviewActions taskId={1} tests={[result()]} />);
    expect(text()).toMatch(/7 tests passed \(pytest\)/);
  });

  it("does not claim success when tests failed", () => {
    render(<ReviewActions taskId={1} tests={[result({ passed: 2, failed: 3 })]} />);
    expect(text()).toMatch(/3 tests did not pass/);
    expect(text()).not.toMatch(/ready for your review/i);
  });

  it("counts errored tests as not passing", () => {
    render(<ReviewActions taskId={1} tests={[result({ failed: 0, errored: 1 })]} />);
    expect(text()).toMatch(/1 test did not pass/);
  });

  it("defaults to the cautious wording when given nothing", () => {
    render(<ReviewActions taskId={1} />);
    expect(text()).toMatch(/not verified by tests/i);
  });

  it("sums results across suites", () => {
    render(
      <ReviewActions taskId={1} tests={[result({ passed: 4 }), result({ passed: 5 })]} />,
    );
    expect(text()).toMatch(/9 tests passed/);
  });

  it("uses the singular for a single test", () => {
    render(<ReviewActions taskId={1} tests={[result({ passed: 1 })]} />);
    expect(text()).toMatch(/1 test passed/);
  });
});

describe("actions still work", () => {
  it("approves", async () => {
    approveMock.mockResolvedValueOnce({});
    render(<ReviewActions taskId={42} tests={[result()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve & Create PR" }));
    await waitFor(() => expect(approveMock).toHaveBeenCalledWith(42));
  });

  it("surfaces a failure without losing the buttons", async () => {
    approveMock.mockRejectedValueOnce(new Error("patch does not apply"));
    render(<ReviewActions taskId={1} tests={[result()]} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve & Create PR" }));
    await waitFor(() =>
      expect(screen.getByText("patch does not apply")).toBeDefined(),
    );
    expect(screen.getByRole("button", { name: "Approve & Create PR" })).toBeDefined();
  });
});
