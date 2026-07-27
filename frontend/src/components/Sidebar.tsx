"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  IconChart,
  IconChevronLeft,
  IconFolder,
  IconGrid,
  IconMenu,
  IconPlus,
  IconX,
  Logo,
} from "@/components/ui/Icons";
import { UserMenu } from "@/components/UserMenu";
import type { SessionUser } from "@/lib/session";

const COLLAPSE_KEY = "agentforge-sidebar-collapsed";

const NAV = [
  { href: "/", label: "Dashboard", icon: IconGrid },
  { href: "/projects", label: "Projects", icon: IconFolder },
  { href: "/tasks/new", label: "New Task", icon: IconPlus },
  { href: "/usage", label: "Usage", icon: IconChart },
];

function isActive(href: string, pathname: string): boolean {
  if (href === "/") {
    // Task detail pages are part of the dashboard flow.
    return pathname === "/" || (pathname.startsWith("/tasks/") && pathname !== "/tasks/new");
  }
  if (href === "/tasks/new") return pathname === "/tasks/new";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({
  pathname,
  collapsed,
  onNavigate,
}: {
  pathname: string;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <nav aria-label="Main navigation" className="flex flex-1 flex-col gap-1 px-2">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(href, pathname);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={collapsed ? label : undefined}
            className={`group relative flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm font-medium transition-colors duration-150 ${
              active
                ? "bg-accent-soft text-ink"
                : "text-ink-mid hover:bg-surface-2 hover:text-ink"
            } ${collapsed ? "justify-center px-0" : ""}`}
          >
            {active && (
              <motion.span
                layoutId="sidebar-active"
                className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-indigo-400 to-violet-500"
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
              />
            )}
            <Icon
              className={`h-4 w-4 shrink-0 ${active ? "text-accent" : "text-ink-dim group-hover:text-ink-mid"}`}
            />
            {!collapsed && <span>{label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

export function Sidebar({ user }: { user: SessionUser | null }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Restore the persisted collapse state after mount (avoids SSR mismatch).
  useEffect(() => {
    setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      localStorage.setItem(COLLAPSE_KEY, prev ? "0" : "1");
      return !prev;
    });
  }

  // Close the mobile drawer on Escape.
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobileOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  return (
    <>
      {/* Desktop sidebar */}
      <motion.aside
        animate={{ width: collapsed ? 64 : 232 }}
        initial={false}
        transition={{ type: "spring", stiffness: 400, damping: 40 }}
        className="glass sticky top-0 z-40 hidden h-screen shrink-0 flex-col border-r border-line md:flex"
      >
        <div
          className={`flex h-16 items-center gap-2.5 px-4 ${collapsed ? "justify-center px-0" : ""}`}
        >
          <Logo className="h-7 w-7 shrink-0" />
          {!collapsed && (
            <span className="text-[15px] font-semibold tracking-tight text-ink">
              AgentForge
            </span>
          )}
        </div>

        <NavLinks pathname={pathname} collapsed={collapsed} />

        {user && <UserMenu user={user} collapsed={collapsed} />}

        <div className={`px-2 pb-4 ${collapsed ? "flex justify-center px-0" : ""}`}>
          <button
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            className="flex w-full items-center justify-center gap-2 rounded-[10px] px-3 py-2 text-xs font-medium text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <IconChevronLeft
              className={`h-4 w-4 transition-transform duration-300 ${collapsed ? "rotate-180" : ""}`}
            />
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </motion.aside>

      {/* Mobile top bar */}
      <div className="glass sticky top-0 z-40 flex h-14 items-center justify-between border-b border-line px-4 md:hidden">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo className="h-7 w-7" />
          <span className="text-[15px] font-semibold tracking-tight text-ink">
            AgentForge
          </span>
        </Link>
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation menu"
          className="rounded-[10px] p-2 text-ink-mid hover:bg-surface-2 hover:text-ink"
        >
          <IconMenu className="h-5 w-5" />
        </button>
      </div>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-40 bg-black/60 md:hidden"
              aria-hidden
            />
            <motion.aside
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: "spring", stiffness: 400, damping: 40 }}
              role="dialog"
              aria-label="Navigation menu"
              className="glass fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-line md:hidden"
            >
              <div className="flex h-16 items-center justify-between px-4">
                <span className="flex items-center gap-2.5">
                  <Logo className="h-7 w-7" />
                  <span className="text-[15px] font-semibold tracking-tight text-ink">
                    AgentForge
                  </span>
                </span>
                <button
                  onClick={() => setMobileOpen(false)}
                  aria-label="Close navigation menu"
                  className="rounded-[10px] p-2 text-ink-mid hover:bg-surface-2 hover:text-ink"
                >
                  <IconX className="h-4 w-4" />
                </button>
              </div>
              <NavLinks
                pathname={pathname}
                collapsed={false}
                onNavigate={() => setMobileOpen(false)}
              />
              {user && <UserMenu user={user} />}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
