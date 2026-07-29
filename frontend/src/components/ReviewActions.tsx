"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { approveTask, rejectTask } from "@/lib/api";

/** Just enough of a test result to describe what was verified. */
type TestSummary = { suite: string; passed: number; failed: number; errored: number };

/**
 * What the run actually proved, in one line.
 *
 * This used to say "Tests passed" unconditionally, directly above a banner
 * warning that no test command had been detected. Both were true — nothing
 * failed because nothing ran — but together they invited approving an
 * unverified diff on the strength of a reassurance nobody had earned.
 */
function verdict(tests: TestSummary[]): { headline: string; reassuring: boolean } {
  if (tests.length === 0) {
    return {
      headline: "Not verified by tests — read the changes below before approving.",
      reassuring: false,
    };
  }
  const failed = tests.reduce((n, t) => n + t.failed + t.errored, 0);
  if (failed > 0) {
    return {
      headline: `${failed} test${failed === 1 ? "" : "s"} did not pass — read the changes below carefully.`,
      reassuring: false,
    };
  }
  const passed = tests.reduce((n, t) => n + t.passed, 0);
  const suite = tests[0].suite;
  return {
    headline: `${passed} test${passed === 1 ? "" : "s"} passed (${suite}) — the changes below are ready for your review.`,
    reassuring: true,
  };
}

export function ReviewActions({
  taskId,
  tests = [],
}: {
  taskId: number;
  /** Results from the run. Empty means no suite ran at all. */
  tests?: TestSummary[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { headline, reassuring } = verdict(tests);

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
    <div
      className={`card px-5 py-4 ${
        reassuring
          ? "border-violet-500/25 bg-violet-500/[0.06]"
          : "border-amber-500/25 bg-amber-500/[0.06]"
      }`}
    >
      <p
        className={`text-sm font-medium ${
          reassuring ? "text-violet-200" : "text-amber-200"
        }`}
      >
        {headline}
      </p>
      <p
        className={`mt-0.5 text-xs ${
          reassuring ? "text-violet-300/70" : "text-amber-300/70"
        }`}
      >
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
