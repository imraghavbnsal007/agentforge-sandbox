"""GitHub App private-key loading and JWT generation.

The recurring assertion: no failure path ever quotes key material.
"""

import time

import pytest

from app.core.config import settings
from app.services.github_app_auth import (
    JWT_CLOCK_SKEW_SECONDS,
    JWT_LIFETIME_SECONDS,
    GitHubAppConfigError,
    generate_app_jwt,
    load_private_key,
    reset_private_key_cache,
)


@pytest.fixture(autouse=True)
def _clean_key_cache():
    reset_private_key_cache()
    yield
    reset_private_key_cache()


@pytest.fixture
def rsa_key_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A real RSA key on disk — the JWT must actually verify."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    path = tmp_path / "app.pem"
    path.write_text(pem)

    monkeypatch.setattr(settings, "github_app_private_key_path", str(path))
    monkeypatch.setattr(settings, "github_app_id", "123456")
    return str(path)


# -- load_private_key -------------------------------------------------------


def test_loads_key_from_configured_path(rsa_key_file):
    assert "PRIVATE KEY" in load_private_key()


def test_unset_path_names_the_setting(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "github_app_private_key_path", "")
    with pytest.raises(GitHubAppConfigError, match="GITHUB_APP_PRIVATE_KEY_PATH"):
        load_private_key()


def test_missing_file_names_the_path(monkeypatch: pytest.MonkeyPatch, tmp_path):
    missing = str(tmp_path / "nope.pem")
    monkeypatch.setattr(settings, "github_app_private_key_path", missing)
    with pytest.raises(GitHubAppConfigError, match="not readable"):
        load_private_key()


def test_non_pem_file_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path):
    path = tmp_path / "notakey.txt"
    path.write_text("just some text")
    monkeypatch.setattr(settings, "github_app_private_key_path", str(path))
    with pytest.raises(GitHubAppConfigError, match="does not look like a PEM"):
        load_private_key()


def test_key_is_cached_and_not_reread(rsa_key_file, monkeypatch: pytest.MonkeyPatch):
    first = load_private_key()
    # Reading again after the file is gone proves the cache served it.
    import os

    os.remove(rsa_key_file)
    assert load_private_key() == first


def test_cache_reset_forces_a_reread(rsa_key_file):
    load_private_key()
    reset_private_key_cache()
    assert "PRIVATE KEY" in load_private_key()


# -- generate_app_jwt -------------------------------------------------------


def test_jwt_has_correct_claims_and_verifies(rsa_key_file):
    import jwt
    from cryptography.hazmat.primitives import serialization

    now = time.time()
    token = generate_app_jwt(now=now)

    private_key = serialization.load_pem_private_key(
        load_private_key().encode(), password=None
    )
    decoded = jwt.decode(
        token,
        private_key.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False},
    )

    assert decoded["iss"] == "123456"
    # iat is backdated to absorb clock skew against GitHub.
    assert decoded["iat"] == int(now) - JWT_CLOCK_SKEW_SECONDS
    assert decoded["exp"] == int(now) + JWT_LIFETIME_SECONDS


def test_jwt_lifetime_stays_inside_githubs_ten_minute_cap():
    assert JWT_LIFETIME_SECONDS < 600


def test_jwt_requires_the_app_id(rsa_key_file, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "github_app_id", "")
    with pytest.raises(GitHubAppConfigError, match="GITHUB_APP_ID"):
        generate_app_jwt()


def test_malformed_key_error_never_leaks_key_material(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    secret = "-----BEGIN PRIVATE KEY-----\nSUPERSECRETNOTAREALKEY\n-----END PRIVATE KEY-----"
    path = tmp_path / "broken.pem"
    path.write_text(secret)
    monkeypatch.setattr(settings, "github_app_private_key_path", str(path))
    monkeypatch.setattr(settings, "github_app_id", "1")

    with pytest.raises(GitHubAppConfigError) as excinfo:
        generate_app_jwt()

    message = str(excinfo.value)
    assert "SUPERSECRETNOTAREALKEY" not in message
    assert "not a valid RSA key" in message
