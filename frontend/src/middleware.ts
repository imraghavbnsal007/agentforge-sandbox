import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Server-to-server base URL (inside Docker Compose this is http://backend:8000).
const API_URL = process.env.API_URL ?? "http://localhost:8000";

/**
 * Redirect signed-out visitors to the landing page.
 *
 * This is navigation UX, not the security boundary — the backend independently
 * rejects unauthenticated API calls with 401. Validating against /auth/me
 * (rather than merely checking that a cookie exists) means an expired or
 * revoked session is caught here too, instead of rendering a broken page.
 *
 * In AUTH_MODE=local the endpoint always reports an authenticated local user,
 * so every request passes through untouched.
 */
export async function middleware(request: NextRequest) {
  const cookie = request.headers.get("cookie") ?? "";

  let authenticated = false;
  try {
    const res = await fetch(`${API_URL}/api/v1/auth/me`, {
      cache: "no-store",
      headers: cookie ? { cookie } : undefined,
    });
    if (res.ok) {
      authenticated = Boolean((await res.json()).authenticated);
    }
  } catch {
    // Backend unreachable: fall through to the landing page rather than
    // rendering an app shell that cannot load any data.
    authenticated = false;
  }

  if (authenticated) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except the landing page, Next internals, and static assets.
  matcher: ["/((?!login|_next/static|_next/image|favicon.ico).*)"],
};
