"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Spinner } from "@/components/ui/Button";
import { logout } from "@/lib/api";
import type { SessionUser } from "@/lib/session";

export function UserMenu({
  user,
  collapsed = false,
}: {
  user: SessionUser;
  /** Sidebar is collapsed — show the avatar only. */
  collapsed?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const label = user.display_name || user.github_login;
  const initial = (label || "?").charAt(0).toUpperCase();

  async function onSignOut() {
    setBusy(true);
    try {
      await logout();
      router.replace("/login");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={`flex items-center gap-2 border-t border-line px-3 py-3 ${
        collapsed ? "justify-center" : ""
      }`}
    >
      {user.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={user.avatar_url}
          alt=""
          className="h-7 w-7 shrink-0 rounded-full ring-1 ring-line-strong"
        />
      ) : (
        <span
          aria-hidden
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-3 text-xs font-semibold text-ink-mid ring-1 ring-line-strong"
        >
          {initial}
        </span>
      )}

      {!collapsed && (
        <>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-ink">
              {label}
            </span>
            {!user.is_local && (
              <span className="block truncate text-[11px] text-ink-dim">
                @{user.github_login}
              </span>
            )}
          </span>
          {!user.is_local && (
            <button
              onClick={onSignOut}
              disabled={busy}
              className="rounded-lg px-2 py-1 text-[11px] font-medium text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/60 disabled:opacity-60"
            >
              {busy ? <Spinner className="h-3 w-3" /> : "Sign out"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
