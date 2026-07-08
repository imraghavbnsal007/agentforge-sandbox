"use client";

import { useEffect } from "react";

const RELOAD_GUARD_KEY = "agentforge-chunk-reload-at";
const MIN_RELOAD_INTERVAL_MS = 10_000;

function isChunkError(reason: unknown): boolean {
  const message =
    reason instanceof Error ? `${reason.name} ${reason.message}` : String(reason);
  return /ChunkLoadError|Loading chunk .* failed|Failed to fetch dynamically imported module|Importing a module script failed/i.test(
    message,
  );
}

/** After a dev-server rebuild/restart, a tab holding old HTML may request
 *  hashed chunks that no longer exist. One reload fixes it — do that
 *  automatically, with a guard so a genuinely broken build can't reload-loop. */
export function ChunkGuard() {
  useEffect(() => {
    function reloadOnce() {
      const last = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) ?? 0);
      if (Date.now() - last < MIN_RELOAD_INTERVAL_MS) return;
      sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()));
      window.location.reload();
    }

    function onError(event: ErrorEvent) {
      if (isChunkError(event.error ?? event.message)) reloadOnce();
    }
    function onRejection(event: PromiseRejectionEvent) {
      if (isChunkError(event.reason)) reloadOnce();
    }

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
