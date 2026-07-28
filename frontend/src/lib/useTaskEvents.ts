"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getTaskEvents, taskStreamUrl, type TaskEvent } from "@/lib/api";

export type StreamState = "connecting" | "live" | "polling" | "disconnected";

const POLL_INTERVAL_MS = 3000;
/** Give up on SSE after this many consecutive failures and fall back. */
const MAX_SSE_FAILURES = 3;

interface Options {
  taskId: number;
  /** Stop streaming once the task can no longer change. */
  terminal?: boolean;
}

/**
 * Live task events, with a polling fallback.
 *
 * The stream is a convenience, never the source of truth: history is loaded
 * from the API first, and every live event is deduplicated by id against what
 * we already have. If SSE cannot be established — a proxy that buffers, a
 * browser without EventSource, Redis down — this degrades to polling the same
 * endpoint rather than showing a broken page.
 */
export function useTaskEvents({ taskId, terminal = false }: Options) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const cursorRef = useRef(0);
  const failuresRef = useRef(0);
  const sourceRef = useRef<EventSource | null>(null);

  /** Append only events we have not already seen, keeping id order. */
  const merge = useCallback((incoming: TaskEvent[]) => {
    if (incoming.length === 0) return;
    setEvents((previous) => {
      const seen = new Set(previous.map((e) => e.id));
      const added = incoming.filter((e) => !seen.has(e.id));
      if (added.length === 0) return previous;
      const next = [...previous, ...added].sort((a, b) => a.id - b.id);
      cursorRef.current = Math.max(cursorRef.current, next[next.length - 1].id);
      return next;
    });
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const page = await getTaskEvents(taskId, cursorRef.current);
      merge(page.events);
      return true;
    } catch {
      return false;
    }
  }, [taskId, merge]);

  // Initial catch-up, always from the durable log.
  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  // Live stream, with fallback.
  useEffect(() => {
    if (terminal) {
      setState("disconnected");
      return;
    }
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setState("polling");
      return;
    }

    let cancelled = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    function startPolling() {
      if (pollTimer) return;
      setState("polling");
      pollTimer = setInterval(() => void loadHistory(), POLL_INTERVAL_MS);
    }

    function connect() {
      if (cancelled) return;
      const source = new EventSource(
        taskStreamUrl(taskId, cursorRef.current),
        { withCredentials: true },
      );
      sourceRef.current = source;

      source.onopen = () => {
        failuresRef.current = 0;
        setState("live");
      };

      source.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data) as TaskEvent & {
            metadata?: Record<string, unknown>;
          };
          if (typeof payload.id !== "number") return;
          merge([{ ...payload, safe_metadata: payload.metadata ?? null }]);
        } catch {
          // A malformed frame must not tear down the stream.
        }
      };

      source.onerror = () => {
        source.close();
        sourceRef.current = null;
        failuresRef.current += 1;
        if (cancelled) return;
        if (failuresRef.current >= MAX_SSE_FAILURES) {
          // Streaming is not working here; poll instead of retrying forever.
          startPolling();
          return;
        }
        setState("connecting");
        // The browser would reconnect on its own, but we re-create the source
        // so the cursor in the URL reflects what we have actually received.
        setTimeout(connect, 1000 * failuresRef.current);
      };
    }

    connect();

    return () => {
      cancelled = true;
      sourceRef.current?.close();
      sourceRef.current = null;
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [taskId, terminal, loadHistory, merge]);

  const reconnect = useCallback(() => {
    failuresRef.current = 0;
    sourceRef.current?.close();
    sourceRef.current = null;
    setState("connecting");
    void loadHistory();
  }, [loadHistory]);

  const latest = events.length > 0 ? events[events.length - 1] : null;
  const progress =
    [...events].reverse().find((e) => typeof e.progress === "number")?.progress ??
    null;
  const stage = [...events].reverse().find((e) => e.stage)?.stage ?? null;

  return { events, state, latest, progress, stage, reconnect };
}
