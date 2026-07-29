import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteTaskDialog } from "@/components/DeleteTaskDialog";

afterEach(cleanup);

function setup(overrides: Partial<Parameters<typeof DeleteTaskDialog>[0]> = {}) {
  const onCancel = vi.fn();
  const onConfirm = vi.fn();
  render(
    <DeleteTaskDialog
      taskTitle="Add multiply"
      busy={false}
      error={null}
      onCancel={onCancel}
      onConfirm={onConfirm}
      {...overrides}
    />,
  );
  return { onCancel, onConfirm };
}

describe("content", () => {
  it("asks the question and names the task", () => {
    setup();
    expect(screen.getByText("Delete Task?")).toBeDefined();
    expect(screen.getByText("Add multiply")).toBeDefined();
  });

  it("states plainly that GitHub is not affected", () => {
    setup();
    const text = screen.getByRole("dialog").textContent ?? "";
    expect(text).toMatch(/NOT/);
    expect(text).toMatch(/Repository code and GitHub commits/i);
    expect(text).toMatch(/pull request this task opened stays open/i);
  });

  it("is announced as a modal dialog", () => {
    setup();
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });
});

describe("actions", () => {
  it("cancels without deleting", () => {
    const { onCancel, onConfirm } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("confirms deletion", () => {
    const { onConfirm } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Delete Task" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const { onCancel } = setup();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });

  it("focuses the confirm button for keyboard use", () => {
    setup();
    expect(document.activeElement?.textContent).toBe("Delete Task");
  });
});

describe("busy and error states", () => {
  it("disables both buttons while deleting", () => {
    setup({ busy: true });
    const buttons = screen.getAllByRole("button") as HTMLButtonElement[];
    expect(buttons).toHaveLength(2);
    expect(buttons.every((b) => b.disabled)).toBe(true);
  });

  it("does not close on Escape while deleting", () => {
    const { onCancel } = setup({ busy: true });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("shows a friendly error without dismissing the dialog", () => {
    setup({ error: "This task is still running. Cancel it first, then delete." });
    expect(screen.getByRole("alert").textContent).toMatch(/still running/);
    expect(screen.getByText("Delete Task?")).toBeDefined();
  });
});
