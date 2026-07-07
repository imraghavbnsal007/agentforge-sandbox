"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { approveTask, rejectTask } from "@/lib/api";

export function ReviewActions({ taskId }: { taskId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(kind: "approve" | "reject") {
    if (kind === "reject" && !confirm("Reject these changes? No PR will be created.")) {
      return;
    }
    setBusy(kind);
    setError(null);
    try {
      await (kind === "approve" ? approveTask(taskId) : rejectTask(taskId));
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-4">
      <p className="text-sm font-medium text-indigo-900">
        Tests passed — the changes below are ready for your review.
      </p>
      <p className="mt-0.5 text-xs text-indigo-700">
        Approving creates a branch, commits the diff, pushes, and opens a pull
        request on GitHub.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={() => act("approve")}
          disabled={busy !== null}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {busy === "approve" ? "Publishing…" : "Approve & Create PR"}
        </button>
        <button
          onClick={() => act("reject")}
          disabled={busy !== null}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
        {error && <span className="text-xs text-red-600">{error}</span>}
      </div>
    </div>
  );
}
