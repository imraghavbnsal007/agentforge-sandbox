"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { IconRetry } from "@/components/ui/Icons";
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
      <Button variant="secondary" size="sm" onClick={onClick} loading={busy}>
        {!busy && <IconRetry className="h-3.5 w-3.5" />}
        {busy ? "Retrying…" : "Retry Task"}
      </Button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </span>
  );
}
