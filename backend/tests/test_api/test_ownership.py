"""The central ownership helper.

Phase 6A ships and proves this mechanism; it is wired into the project and
task routes in Phase 6C, once migration 0011 adds Project.user_id.
"""

from dataclasses import dataclass

import pytest

from app.api.deps import ensure_owned
from app.core.exceptions import NotFoundError
from app.models import User


@dataclass
class OwnedRow:
    id: int
    user_id: int


@dataclass
class UnownedRow:
    id: int


def _user(user_id: int) -> User:
    return User(id=user_id, github_user_id=user_id, github_login=f"u{user_id}")


def test_owner_may_access_their_own_row():
    row = OwnedRow(id=1, user_id=10)
    assert ensure_owned(row, _user(10)) is row


def test_another_users_row_raises_not_found_not_forbidden():
    """404, never 403 — a 403 would confirm the row exists."""
    with pytest.raises(NotFoundError):
        ensure_owned(OwnedRow(id=1, user_id=10), _user(11))


def test_not_found_message_reveals_nothing():
    with pytest.raises(NotFoundError) as excinfo:
        ensure_owned(OwnedRow(id=99, user_id=10), _user(11))
    message = str(excinfo.value)
    assert "99" not in message
    assert "10" not in message


def test_rows_without_an_owner_column_stay_visible():
    """Pre-6C rows have no user_id; treating them as visible is what keeps
    local mode working until ownership lands."""
    row = UnownedRow(id=1)
    assert ensure_owned(row, _user(10)) is row
