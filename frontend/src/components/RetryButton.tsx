"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { retryTask } from "@/lib/api";

export function RetryButton({ taskId }: { taskId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      await retryTask(taskId);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={onClick}
        disabled={busy}
        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      >
        {busy ? "Retrying…" : "↻ Retry Task"}
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </span>
  );
}
