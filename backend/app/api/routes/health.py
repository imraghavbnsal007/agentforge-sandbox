from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Response

from app.core.config import settings

router = APIRouter()

# Read-only bind mount from the host's backups/ directory (docker-compose).
BACKUPS_DIR = Path("/backups")


def _backup_diagnostics() -> dict:
    """Backup freshness for ops visibility; never fails the health check."""
    try:
        if not BACKUPS_DIR.is_dir():
            return {"available": False}
        dumps = sorted(
            BACKUPS_DIR.glob("*.sql"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        info: dict = {"available": True, "count": len(dumps)}
        if dumps:
            latest = dumps[0]
            info["latest"] = latest.name
            info["latest_age_hours"] = round(
                (
                    datetime.now(timezone.utc)
                    - datetime.fromtimestamp(
                        latest.stat().st_mtime, tz=timezone.utc
                    )
                ).total_seconds()
                / 3600,
                1,
            )
        return info
    except OSError:
        return {"available": False}


@router.get("/health")
async def health() -> dict:
    """Liveness. Deliberately depends on nothing external — not the database,
    not Redis, and never GitHub. A liveness probe that fails when a
    dependency blips would restart a perfectly healthy process."""
    return {"status": "ok", "backups": _backup_diagnostics()}


@router.get("/ready")
async def ready(response: Response, request: Request) -> dict:
    """Readiness: can this instance actually serve traffic?

    Checks the dependencies a request genuinely needs — PostgreSQL, Redis,
    and a validated configuration — and reports the migration revision and
    auth mode for operators. Returns 503 when a required dependency is down
    so a load balancer stops sending traffic here.

    GitHub is deliberately NOT probed: it is an upstream we call on demand,
    not a dependency of being able to serve.
    """
    from sqlalchemy import text

    from app.core.startup_checks import check_configuration
    from app.db.session import async_session_factory

    checks: dict[str, dict] = {}

    # PostgreSQL
    revision = None
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            revision = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        checks["database"] = {"ok": True}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}

    # Redis — sessions, OAuth state and installation-token caching need it.
    try:
        kv = getattr(request.app.state, "kv", None)
        if kv is None:
            checks["redis"] = {"ok": False, "error": "not_initialised"}
        else:
            await kv.set("agentforge:readiness", "1", 10)
            await kv.get("agentforge:readiness")
            checks["redis"] = {"ok": True}
    except Exception as exc:
        checks["redis"] = {"ok": False, "error": type(exc).__name__}

    # Configuration
    report = check_configuration()
    checks["configuration"] = {
        "ok": report.ok,
        # Names of failing settings only — never their values.
        "problems": report.errors,
    }

    ready_now = all(entry["ok"] for entry in checks.values())
    if not ready_now:
        response.status_code = 503

    return {
        "ready": ready_now,
        "auth_mode": settings.auth_mode,
        "environment": settings.app_env,
        "version": _version(),
        "migration_revision": revision,
        "checks": checks,
    }


def _version() -> str:
    """Build identifier, if the deployment provides one."""
    import os

    return os.environ.get("AGENTFORGE_VERSION", "dev")
