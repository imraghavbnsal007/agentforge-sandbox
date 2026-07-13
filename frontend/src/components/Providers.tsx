"use client";

import { MotionConfig } from "framer-motion";

/** App-wide client context: animations honor the OS reduced-motion setting. */
export function Providers({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
