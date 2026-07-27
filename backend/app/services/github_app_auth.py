"""GitHub App identity: private-key loading and RS256 JWT generation.

The App's private key is the root credential of the whole installation-token
chain. Rules enforced here:

  * loaded from a file path only — never from the database, never from a
    request, never echoed back to a caller;
  * read once and cached in memory, so a key file can be mounted read-only;
  * never logged, and never included in an exception message. Failures name
    the *path* and the *reason*, never the contents.

App JWTs are short-lived by construction: GitHub rejects anything longer
than 10 minutes, and we ask for less.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# GitHub caps app JWTs at 10 minutes. Stay comfortably inside it.
JWT_LIFETIME_SECONDS = 540
# Backdate `iat` to absorb clock skew between us and GitHub.
JWT_CLOCK_SKEW_SECONDS = 60


class GitHubAppConfigError(Exception):
    """The App credentials are missing or unusable. Safe to show an operator:
    names the setting or path at fault, never key material."""


@dataclass
class _CachedKey:
    path: str
    mtime: float
    pem: str


_key_cache: _CachedKey | None = None


def reset_private_key_cache() -> None:
    """Drop the in-memory key. Used by tests and after a key rotation."""
    global _key_cache
    _key_cache = None


def load_private_key() -> str:
    """Return the PEM contents, reading from disk at most once per file version.

    Raises GitHubAppConfigError with an operator-actionable message when the
    path is unset, missing, unreadable, or not a PEM private key.
    """
    global _key_cache

    path_value = settings.github_app_private_key_path
    if not path_value:
        raise GitHubAppConfigError(
            "GITHUB_APP_PRIVATE_KEY_PATH is not set — required to authenticate "
            "as the GitHub App."
        )
    path = Path(path_value)
    cached = _key_cache if (_key_cache and _key_cache.path == path_value) else None

    try:
        stat = path.stat()
    except OSError as exc:
        # A mounted secret can briefly vanish (remount, rotation). Keep
        # serving the cached key rather than failing every GitHub operation —
        # GitHub, not the filesystem, is the authority on whether a key is
        # still valid. Only fail when there is nothing cached to fall back to.
        if cached is not None:
            logger.warning(
                "GitHub App private key at %s is momentarily unreadable (%s); "
                "using the cached key",
                path_value,
                type(exc).__name__,
            )
            return cached.pem
        raise GitHubAppConfigError(
            f"GitHub App private key not readable at {path_value!r}: "
            f"{type(exc).__name__}. Check the path and the container mount."
        ) from exc

    # mtime change means the key was rotated — re-read.
    if cached is not None and cached.mtime == stat.st_mtime:
        return cached.pem

    try:
        pem = path.read_text()
    except OSError as exc:
        raise GitHubAppConfigError(
            f"GitHub App private key not readable at {path_value!r}: "
            f"{type(exc).__name__}."
        ) from exc

    # Shape check only — the contents never appear in the error.
    if "PRIVATE KEY" not in pem:
        raise GitHubAppConfigError(
            f"File at {path_value!r} does not look like a PEM private key. "
            "Download the .pem from the GitHub App settings page."
        )

    _key_cache = _CachedKey(path=path_value, mtime=stat.st_mtime, pem=pem)
    logger.info("Loaded GitHub App private key from %s", path_value)
    return pem


def generate_app_jwt(now: float | None = None) -> str:
    """Sign a short-lived RS256 JWT identifying AgentForge as the GitHub App.

    This JWT authenticates *the app*, not any installation. It is only ever
    used to call app-level endpoints (read an installation, mint an
    installation token) — never for repository access.
    """
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise GitHubAppConfigError(
            "PyJWT is not installed in the backend image."
        ) from exc

    app_id = settings.github_app_id
    if not app_id:
        raise GitHubAppConfigError(
            "GITHUB_APP_ID is not set — required to authenticate as the "
            "GitHub App."
        )

    issued_at = int(now if now is not None else time.time())
    payload = {
        "iat": issued_at - JWT_CLOCK_SKEW_SECONDS,
        "exp": issued_at + JWT_LIFETIME_SECONDS,
        "iss": str(app_id),
    }
    try:
        return jwt.encode(payload, load_private_key(), algorithm="RS256")
    except GitHubAppConfigError:
        raise
    except Exception as exc:
        # A malformed key surfaces here. The exception text from the crypto
        # layer can echo key material, so it is deliberately not included.
        raise GitHubAppConfigError(
            "Could not sign the GitHub App JWT — the private key at "
            f"{settings.github_app_private_key_path!r} is not a valid RSA key "
            f"({type(exc).__name__})."
        ) from None
