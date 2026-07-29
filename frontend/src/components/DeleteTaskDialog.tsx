"use client";

import { useEffect } from "react";

import { Button, Spinner } from "@/components/ui/Button";

/**
 * Confirmation before deleting a task.
 *
 * Deliberately spells out what is *not* affected: the most likely fear is
 * that this touches the repository or an open pull request, and it does not.
 */
export function DeleteTaskDialog({
  taskTitle,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  taskTitle: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  // Escape closes, so the dialog is usable from the keyboard alone.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-task-title"
    >
      <div
        className="absolute inset-0 bg-black/70"
        onClick={() => !busy && onCancel()}
        aria-hidden
      />
      <div className="card relative w-full max-w-md p-6">
        <h2
          id="delete-task-title"
          className="text-lg font-semibold tracking-tight text-ink"
        >
          Delete Task?
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-mid">
          This will permanently remove{" "}
          <span className="font-medium text-ink">{taskTitle}</span> from
          AgentForge.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-ink-dim">
          Repository code and GitHub commits will{" "}
          <span className="font-medium text-ink-mid">NOT</span> be affected. Any
          pull request this task opened stays open.
        </p>

        {error && (
          <p className="mt-4 text-xs text-red-400" role="alert">
            {error}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            autoFocus
            variant="danger"
            size="sm"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? <Spinner className="h-3.5 w-3.5" /> : "Delete Task"}
          </Button>
        </div>
      </div>
    </div>
  );
}
