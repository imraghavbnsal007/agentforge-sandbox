from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

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
    return {"status": "ok", "backups": _backup_diagnostics()}
