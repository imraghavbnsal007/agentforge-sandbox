"""Cookie handling, client-IP resolution, and CSRF protection.

CSRF model: double-submit. The authoritative token lives in the server-side
session; a readable mirror is set as a separate cookie so the frontend can
echo it in the `X-CSRF-Token` header.

Enforcement rule — CSRF is checked **only when the request authenticates via
the session cookie**. A request with no session cookie carries no ambient
authority, so there is nothing for a cross-site forgery to ride on. This is
also what keeps AUTH_MODE=local (and the existing test-suite, which never
sends cookies) working unchanged.
"""

import hmac

from fastapi import Request, Response

from app.core.config import settings

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting and audit records.

    X-Forwarded-For is only consulted when explicitly trusted; otherwise a
    caller could spoof the header to dodge rate limits.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def set_session_cookies(response: Response, session_id: str, csrf_token: str) -> None:
    """Attach the HTTP-only session cookie plus its readable CSRF mirror."""
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    # Readable by design: the frontend must echo it back in a header.
    # Knowing it is harmless; a cross-site attacker cannot read it.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/")


def read_session_cookie(request: Request) -> str:
    return request.cookies.get(settings.session_cookie_name, "")


def csrf_token_matches(request: Request, expected: str) -> bool:
    provided = request.headers.get(CSRF_HEADER, "")
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)
