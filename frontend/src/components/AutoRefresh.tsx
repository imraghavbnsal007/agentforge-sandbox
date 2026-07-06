"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-fetches server component data on an interval so task status
 *  transitions (pending → planning → … → completed) show up live. */
export function AutoRefresh({ intervalMs = 3000 }: { intervalMs?: number }) {
  const router = useRouter();

  useEffect(() => {
    const timer = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [router, intervalMs]);

  return null;
}
