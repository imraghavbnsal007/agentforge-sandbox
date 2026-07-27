import { cookies } from "next/headers";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AuthMode = "local" | "github_app";

export interface SessionUser {
  id: number;
  github_login: string;
  display_name: string | null;
  avatar_url: string | null;
  email: string | null;
  is_local: boolean;
  last_login_at: string | null;
}

export interface AuthStatus {
  auth_mode: AuthMode;
  authenticated: boolean;
  login_available: boolean;
  user: SessionUser | null;
}

/** Signed-out fallback used when the API is unreachable, so the shell can
 *  still render rather than crashing the whole page. */
const SIGNED_OUT: AuthStatus = {
  auth_mode: "github_app",
  authenticated: false,
  login_available: false,
  user: null,
};

/**
 * Read the current auth status server-side, forwarding the browser's cookies
 * so the backend resolves the same session.
 */
export async function getAuthStatus(): Promise<AuthStatus> {
  try {
    const cookieHeader = (await cookies()).toString();
    const res = await fetch(`${API_URL}/api/v1/auth/me`, {
      cache: "no-store",
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    });
    if (!res.ok) return SIGNED_OUT;
    return (await res.json()) as AuthStatus;
  } catch {
    return SIGNED_OUT;
  }
}

/** Where the browser should go to start GitHub sign-in. */
export function loginUrl(redirectTo = "/"): string {
  const target = redirectTo.startsWith("/") && !redirectTo.startsWith("//")
    ? redirectTo
    : "/";
  return `${PUBLIC_API_URL}/api/v1/auth/github/login?redirect_to=${encodeURIComponent(target)}`;
}
