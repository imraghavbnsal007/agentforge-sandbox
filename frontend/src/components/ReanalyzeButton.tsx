"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { analyzeProject } from "@/lib/api";

export function ReanalyzeButton({
  projectId,
  label,
}: {
  projectId: number;
  label: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      await analyzeProject(projectId);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button onClick={onClick} loading={busy}>
        {busy ? "Starting…" : label}
      </Button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </span>
  );
}
