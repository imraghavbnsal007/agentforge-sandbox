"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button, Spinner } from "@/components/ui/Button";
import { IconClock, IconRetry } from "@/components/ui/Icons";
import { cancelTask, retryTask, type RunStage, type TaskStatus } from "@/lib/api";
import { useTaskEvents, type StreamState } from "@/lib/useTaskEvents";

const TERMINAL: TaskStatus[] = [
  "completed",
  "failed",
  "rejected",
  "cancelled",
  "publish_failed",
];
const CANCELLABLE: TaskStatus[] = [
  "pending",
  "planning",
  "coding",
  "testing",
  "publishing",
];
const RETRYABLE: TaskStatus[] = [
  "failed",
  "cancelled",
  "publish_failed",
  "rejected",
  "ready_for_review",
];

const STAGE_LABEL: Record<RunStage, string> = {
  queued: "Queued",
  preparing: "Preparing workspace",
  cloning: "Cloning repository",
  analysing: "Analysing repository",
  planning: "Planning the change",
  generating: "Generating changes",
  testing: "Running tests",
  summarising: "Writing the summary",
  awaiting_review: "Ready for review",
  pushing: "Pushing branch",
  creating_pr: "Creating pull request",
  completed: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};

const CONNECTION_LABEL: Record<StreamState, string> = {
  connecting: "Connecting…",
  live: "Live",
  polling: "Updating periodically",
  disconnected: "Not updating",
};

function ConnectionPill({
  state,
  onReconnect,
}: {
  state: StreamState;
  onReconnect: () => void;
}) {
  const tone =
    state === "live"
      ? "bg-emerald-500/12 text-emerald-300 ring-emerald-400/25"
      : state === "polling"
        ? "bg-amber-500/12 text-amber-300 ring-amber-400/25"
        : "bg-slate-500/12 text-slate-300 ring-slate-400/25";
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${tone}`}
        role="status"
        aria-live="polite"
      >
        {state === "live" && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
        )}
        {CONNECTION_LABEL[state]}
      </span>
      {(state === "polling" || state === "disconnected") && (
        <button
          onClick={onReconnect}
          className="rounded-lg px-2 py-0.5 text-[11px] font-medium text-ink-dim underline-offset-2 transition-colors hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60"
        >
          Reconnect
        </button>
      )}
    </span>
  );
}

function Elapsed({ since, stop }: { since: string; stop: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stop) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [stop]);

  const seconds = Math.max(
    0,
    Math.floor((now - new Date(since).getTime()) / 1000),
  );
  const text =
    seconds < 60
      ? `${seconds}s`
      : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums">
      <IconClock className="h-3.5 w-3.5" />
      {text}
    </span>
  );
}

/**
 * Live execution panel: stage, progress, controls and an event timeline.
 *
 * Deliberately additive — it sits alongside the existing task detail content
 * rather than replacing it, so nothing that already worked is disturbed.
 */
export function TaskLivePanel({
  taskId,
  status,
  startedAt,
}: {
  taskId: number;
  status: TaskStatus;
  startedAt: string;
}) {
  const router = useRouter();
  const terminal = TERMINAL.includes(status);
  const { events, state, latest, progress, stage, reconnect } = useTaskEvents({
    taskId,
    terminal,
  });

  const [busy, setBusy] = useState<"cancel" | "retry" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelRequested, setCancelRequested] = useState(false);
  const timelineRef = useRef<HTMLOListElement>(null);

  // A finished run means the server has data the page was rendered without.
  const lastEventId = latest?.id ?? 0;
  const previousId = useRef(lastEventId);
  useEffect(() => {
    if (lastEventId !== previousId.current) {
      previousId.current = lastEventId;
      if (
        latest &&
        ["review_ready", "run_failed", "run_cancelled", "pr_created"].includes(
          latest.event_type,
        )
      ) {
        router.refresh();
      }
    }
  }, [lastEventId, latest, router]);

  async function onCancel() {
    if (!window.confirm("Cancel this task? The agent will stop at its next safe point.")) {
      return;
    }
    setBusy("cancel");
    setError(null);
    try {
      await cancelTask(taskId);
      setCancelRequested(true);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel");
    } finally {
      setBusy(null);
    }
  }

  async function onRetry() {
    setBusy("retry");
    setError(null);
    try {
      await retryTask(taskId);
      setCancelRequested(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not retry");
    } finally {
      setBusy(null);
    }
  }

  const shownProgress = progress ?? (terminal ? 100 : 0);
  const stageLabel = stage ? STAGE_LABEL[stage] : null;

  return (
    <section className="card p-5" aria-labelledby="live-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3
          id="live-heading"
          className="text-[13px] font-semibold uppercase tracking-wide text-ink-dim"
        >
          Execution
        </h3>
        <ConnectionPill state={state} onReconnect={reconnect} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-mid">
        <span className="text-sm font-medium text-ink">
          {stageLabel ?? (terminal ? "Finished" : "Waiting to start")}
        </span>
        <Elapsed since={startedAt} stop={terminal} />
        {latest?.safe_metadata?.files_changed != null && (
          <span>{String(latest.safe_metadata.files_changed)} file(s) changed</span>
        )}
      </div>

      <div
        className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-3"
        role="progressbar"
        aria-valuenow={shownProgress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Execution progress: ${stageLabel ?? status}`}
      >
        <div
          className={`h-full rounded-full bg-gradient-to-r transition-[width] duration-500 ${
            status === "failed" || status === "publish_failed"
              ? "from-red-500 to-red-400"
              : status === "cancelled"
                ? "from-slate-600 to-slate-500"
                : "from-indigo-500 to-blue-400"
          }`}
          style={{ width: `${shownProgress}%` }}
        />
      </div>

      {cancelRequested && !terminal && (
        <p className="mt-3 text-xs text-amber-300" role="status">
          Cancellation requested — stopping at the next safe checkpoint.
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-red-400" role="alert">
          {error}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {CANCELLABLE.includes(status) && (
          <Button
            variant="danger"
            size="sm"
            onClick={onCancel}
            disabled={busy !== null || cancelRequested}
          >
            {busy === "cancel" ? <Spinner className="h-3.5 w-3.5" /> : "Cancel"}
          </Button>
        )}
        {RETRYABLE.includes(status) && (
          <Button
            variant="secondary"
            size="sm"
            onClick={onRetry}
            disabled={busy !== null}
          >
            {busy === "retry" ? (
              <Spinner className="h-3.5 w-3.5" />
            ) : (
              <IconRetry className="h-3.5 w-3.5" />
            )}
            Retry
          </Button>
        )}
      </div>

      {events.length > 0 && (
        <ol
          ref={timelineRef}
          className="mt-5 max-h-72 space-y-1.5 overflow-y-auto border-t border-line pt-4"
          aria-label="Execution timeline"
        >
          {events.map((event) => (
            <li
              key={event.id}
              className="flex items-baseline gap-3 text-xs text-ink-mid"
            >
              <span className="shrink-0 tabular-nums text-ink-dim">
                {new Date(event.created_at).toLocaleTimeString()}
              </span>
              <span
                className={
                  event.error_code ? "text-red-400" : "text-ink-mid"
                }
              >
                {event.message ?? event.event_type.replaceAll("_", " ")}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
