import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import require_user
from app.api.routes import (
    auth,
    github_app,
    github_webhooks,
    health,
    llm,
    meta,
    projects,
    repositories,
    tasks,
    usage,
)
from app.core.audit import CSRF_REJECTED, RATE_LIMITED, audit
from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)
from app.core.security import (
    SAFE_METHODS,
    client_ip,
    csrf_token_matches,
    read_session_cookie,
)
from app.services.kv_store import InMemoryKVStore, RedisKVStore
from app.services.session_store import SessionStore

logger = logging.getLogger(__name__)

# Routes that never carry a browser session and must not be CSRF-gated.
CSRF_EXEMPT_PREFIXES = ("/api/v1/auth/github/",)


def _validate_cors_config() -> list[str]:
    """Credentialed CORS with a wildcard origin is never valid — browsers
    reject it and it would defeat the point. Fail loudly at startup."""
    origins = settings.cors_origin_list()
    if "*" in origins:
        raise RuntimeError(
            "CORS_ORIGINS must list explicit origins: '*' cannot be combined "
            "with credentialed requests."
        )
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    # Sessions, OAuth state and rate limits share one Redis client, separate
    # from the arq job queue's pool.
    import redis.asyncio as redis_asyncio

    app.state.redis = redis_asyncio.from_url(settings.redis_url)
    app.state.kv = RedisKVStore(app.state.redis)
    yield
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()


def create_app(with_lifespan: bool = True) -> FastAPI:
    origins = _validate_cors_config()
    app = FastAPI(title="AgentForge API", lifespan=lifespan if with_lifespan else None)

    # Replaced by the Redis-backed store in lifespan. Without a lifespan
    # (tests) each app instance gets its own isolated in-memory store.
    app.state.kv = InMemoryKVStore()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def csrf_protection(request: Request, call_next):
        """Double-submit CSRF, enforced only for cookie-authenticated calls.

        A request with no session cookie carries no ambient authority, so
        there is nothing for a forged cross-site request to ride on. That is
        also why AUTH_MODE=local and the existing test-suite are unaffected.
        """
        session_id = read_session_cookie(request)
        needs_check = (
            request.method not in SAFE_METHODS
            and session_id
            and not request.url.path.startswith(CSRF_EXEMPT_PREFIXES)
        )
        if needs_check:
            store = SessionStore(
                request.app.state.kv, ttl_seconds=settings.session_ttl_seconds
            )
            data = await store.get(session_id)
            if data is None or not csrf_token_matches(request, data.csrf_token):
                audit(
                    CSRF_REJECTED,
                    path=request.url.path,
                    method=request.method,
                    ip=client_ip(request),
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing or invalid"},
                )
        return await call_next(request)

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidInputError)
    async def invalid_input_handler(
        request: Request, exc: InvalidInputError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(
        request: Request, exc: UnauthorizedError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(RateLimitedError)
    async def rate_limited_handler(
        request: Request, exc: RateLimitedError
    ) -> JSONResponse:
        audit(RATE_LIMITED, path=request.url.path, ip=client_ip(request))
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    # Open: liveness, server configuration, and sign-in itself.
    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(auth.router)
    # Webhooks authenticate by HMAC signature, not by session — GitHub has no
    # cookie. Deliberately NOT added to CSRF_EXEMPT_PREFIXES: GitHub sends no
    # cookies so CSRF never fires, and a browser-with-session POST here should
    # still be blocked.
    app.include_router(github_webhooks.router)

    # Everything that exposes user data requires a session. In local mode
    # require_user always resolves the default local user, so these behave
    # exactly as they did before Phase 6A.
    protected = [Depends(require_user)]
    app.include_router(github_app.router, dependencies=protected)
    app.include_router(llm.router, dependencies=protected)
    app.include_router(projects.router, dependencies=protected)
    app.include_router(repositories.router, dependencies=protected)
    app.include_router(tasks.router, dependencies=protected)
    app.include_router(usage.router, dependencies=protected)
    return app


app = create_app()
