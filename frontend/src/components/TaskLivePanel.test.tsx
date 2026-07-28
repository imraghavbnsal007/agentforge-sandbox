import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskLivePanel } from "@/components/TaskLivePanel";
import type { TaskEvent } from "@/lib/api";

const getTaskEventsMock = vi.fn();
const cancelTaskMock = vi.fn();
const retryTaskMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getTaskEvents: (...args: unknown[]) => getTaskEventsMock(...args),
    cancelTask: (...args: unknown[]) => cancelTaskMock(...args),
    retryTask: (...args: unknown[]) => retryTaskMock(...args),
    taskStreamUrl: () => "http://test/stream",
  };
});

/** EventSource does not exist in jsdom; this stands in for it. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  emit(event: Partial<TaskEvent> & { id: number }) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
}

function event(overrides: Partial<TaskEvent> & { id: number }): TaskEvent {
  return {
    task_id: 1,
    run_id: 1,
    sequence_number: overrides.id,
    event_type: "stage_changed",
    stage: null,
    message: null,
    progress: null,
    error_code: null,
    safe_metadata: null,
    created_at: "2026-07-28T12:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  getTaskEventsMock.mockResolvedValue({ events: [], next_cursor: null });
  // @ts-expect-error test double
  globalThis.EventSource = FakeEventSource;
});

afterEach(cleanup);

const RUNNING = { taskId: 1, status: "coding" as const, startedAt: "2026-07-28T12:00:00Z" };


describe("stage and progress", () => {
  it("renders replayed history from the API", async () => {
    getTaskEventsMock.mockResolvedValue({
      events: [
        event({ id: 1, stage: "cloning", message: "Cloning repository", progress: 10 }),
      ],
      next_cursor: null,
    });

    render(<TaskLivePanel {...RUNNING} />);

    await waitFor(() =>
      expect(
        screen.getAllByText("Cloning repository").length,
      ).toBeGreaterThan(0),
    );
  });

  it("shows the stage label for the newest event", async () => {
    getTaskEventsMock.mockResolvedValue({
      events: [
        event({ id: 1, stage: "cloning" }),
        event({ id: 2, stage: "generating" }),
      ],
      next_cursor: null,
    });

    render(<TaskLivePanel {...RUNNING} />);

    await waitFor(() =>
      expect(screen.getByText("Generating changes")).toBeDefined(),
    );
  });

  it("reflects progress on the progress bar", async () => {
    getTaskEventsMock.mockResolvedValue({
      events: [event({ id: 1, stage: "testing", progress: 70 })],
      next_cursor: null,
    });

    render(<TaskLivePanel {...RUNNING} />);

    await waitFor(() => {
      const bar = screen.getByRole("progressbar");
      expect(bar.getAttribute("aria-valuenow")).toBe("70");
    });
  });

  it("appends live events from the stream", async () => {
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));

    const source = FakeEventSource.instances[0];
    source.onopen?.();
    source.emit(event({ id: 5, message: "Running tests", stage: "testing" }));

    await waitFor(() =>
      expect(screen.getAllByText("Running tests").length).toBeGreaterThan(0),
    );
  });

  it("ignores a duplicate event id", async () => {
    getTaskEventsMock.mockResolvedValue({
      events: [event({ id: 5, message: "Only once" })],
      next_cursor: null,
    });
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));

    FakeEventSource.instances[0].emit(event({ id: 5, message: "Only once" }));

    await waitFor(() =>
      expect(screen.getAllByText("Only once")).toHaveLength(1),
    );
  });
});

describe("connection state", () => {
  it("reports live once the stream opens", async () => {
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    FakeEventSource.instances[0].onopen?.();

    await waitFor(() => expect(screen.getByText("Live")).toBeDefined());
  });

  it("falls back to polling after repeated stream failures", async () => {
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));

    for (let i = 0; i < 3; i += 1) {
      const latest = FakeEventSource.instances[FakeEventSource.instances.length - 1];
      latest.onerror?.();
    }

    await waitFor(() =>
      expect(screen.getByText("Updating periodically")).toBeDefined(),
    );
  });

  it("offers a reconnect control when not live", async () => {
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    for (let i = 0; i < 3; i += 1) {
      FakeEventSource.instances[FakeEventSource.instances.length - 1].onerror?.();
    }

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Reconnect/i })).toBeDefined(),
    );
  });

  it("does not stream for a finished task", async () => {
    render(<TaskLivePanel taskId={1} status="completed" startedAt="2026-07-28T12:00:00Z" />);
    await waitFor(() => expect(screen.getByText("Not updating")).toBeDefined());
    expect(FakeEventSource.instances.length).toBe(0);
  });
});

describe("controls", () => {
  it("shows Cancel while running and not Retry", async () => {
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cancel" })).toBeDefined(),
    );
    expect(screen.queryByRole("button", { name: /Retry/i })).toBeNull();
  });

  it("shows Retry for a failed task and not Cancel", async () => {
    render(<TaskLivePanel taskId={1} status="failed" startedAt="2026-07-28T12:00:00Z" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Retry/i })).toBeDefined(),
    );
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("confirms before cancelling", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(confirm).toHaveBeenCalled();
    expect(cancelTaskMock).not.toHaveBeenCalled();
  });

  it("cancels and shows the requested state", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    cancelTaskMock.mockResolvedValueOnce({});
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(cancelTaskMock).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.getByText(/Cancellation requested/i)).toBeDefined(),
    );
  });

  it("surfaces a cancel failure without breaking the panel", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    cancelTaskMock.mockRejectedValueOnce(new Error("cannot be cancelled"));
    render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() => screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/cannot be cancelled/),
    );
  });

  it("retries a failed task", async () => {
    retryTaskMock.mockResolvedValueOnce({});
    render(<TaskLivePanel taskId={1} status="failed" startedAt="2026-07-28T12:00:00Z" />);
    await waitFor(() => screen.getByRole("button", { name: /Retry/i }));

    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));

    await waitFor(() => expect(retryTaskMock).toHaveBeenCalledWith(1));
  });
});

describe("secret hygiene", () => {
  it("renders only what the server sent, with no internal fields", async () => {
    getTaskEventsMock.mockResolvedValue({
      events: [
        event({ id: 1, message: "Cloning repository", stage: "cloning" }),
      ],
      next_cursor: null,
    });
    const { container } = render(<TaskLivePanel {...RUNNING} />);
    await waitFor(() =>
      expect(screen.getAllByText("Cloning repository").length).toBeGreaterThan(0),
    );

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/ghs_|gho_|ghp_|Traceback|Bearer /);
  });
});
