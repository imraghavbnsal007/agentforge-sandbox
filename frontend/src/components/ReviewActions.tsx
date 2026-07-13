"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
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
    <div className="card border-violet-500/25 bg-violet-500/[0.06] px-5 py-4">
      <p className="text-sm font-medium text-violet-200">
        Tests passed — the changes below are ready for your review.
      </p>
      <p className="mt-0.5 text-xs text-violet-300/70">
        Approving creates a branch, commits the diff, pushes, and opens a pull
        request on GitHub.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          onClick={() => act("approve")}
          disabled={busy !== null}
          loading={busy === "approve"}
        >
          {busy === "approve" ? "Publishing…" : "Approve & Create PR"}
        </Button>
        <Button
          variant="secondary"
          onClick={() => act("reject")}
          disabled={busy !== null}
          loading={busy === "reject"}
        >
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </Button>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </div>
  );
}
