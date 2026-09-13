"""Tests for the SQLAdmin authentication backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.interfaces.admin import auth as admin_auth
from src.interfaces.admin.auth import AdminAuth
from src.modules.platform.constants import PERM_PLATFORM_ADMIN
from src.modules.platform.service import assign_role, upsert_role
from src.modules.user.models import User


class FakeRequest:
    def __init__(self, form: dict[str, Any]) -> None:
        self._form = form
        self.session: dict[str, Any] = {}

    async def form(self) -> dict[str, Any]:
        return self._form


async def _login(configured: tuple[str, str], form: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    username, password = configured
    request = FakeRequest(form)
    settings = SimpleNamespace(ADMIN_USERNAME=username, ADMIN_PASSWORD=password)
    with patch("src.interfaces.admin.auth.get_settings", return_value=settings):
        authenticated = await AdminAuth(secret_key="test").login(request)
    return authenticated, request.session


@pytest.mark.parametrize(
    ("configured", "form"),
    [
        (("", ""), {"username": "", "password": ""}),
        (("admin", ""), {"username": "admin", "password": ""}),
        (("", "s3cret"), {"username": "", "password": "s3cret"}),
    ],
)
async def test_login_is_disabled_until_both_credentials_are_configured(configured, form):
    authenticated, session = await _login(configured, form)

    assert authenticated is False
    assert session == {}


async def test_login_with_configured_credentials_starts_admin_session():
    authenticated, session = await _login(("admin", "s3cret"), {"username": "admin", "password": "s3cret"})

    assert authenticated is True
    assert session == {"admin_authenticated": True}


@pytest.mark.parametrize(
    "form",
    [
        {"username": "admin", "password": "wrong"},
        {"username": "wrong", "password": "s3cret"},
        {"username": "admin"},
        {},
    ],
)
async def test_login_rejects_wrong_or_missing_credentials(form):
    authenticated, session = await _login(("admin", "s3cret"), form)

    assert authenticated is False
    assert session == {}


async def test_login_rejects_non_ascii_input_without_raising():
    authenticated, session = await _login(("admin", "s3cret"), {"username": "admín", "password": "s3cret"})

    assert authenticated is False
    assert session == {}


async def test_login_accepts_non_ascii_configured_password():
    authenticated, session = await _login(("admin", "contraseña"), {"username": "admin", "password": "contraseña"})

    assert authenticated is True
    assert session == {"admin_authenticated": True}


class SessionRequest:
    """A request that only carries an admin session, which is all ``authenticate`` reads."""

    def __init__(self, session: dict[str, Any]) -> None:
        self.session = session


@pytest.fixture(autouse=True)
def admin_db(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(admin_auth, "local_session", session_factory)


async def test_authenticate_rejects_a_session_that_never_logged_in():
    assert await AdminAuth(secret_key="test").authenticate(SessionRequest({})) is False


async def test_authenticate_keeps_the_break_glass_session(admin_db: None):
    """The configured admin pair has no platform user to re-resolve permissions for."""
    request = SessionRequest({"admin_authenticated": True})

    assert await AdminAuth(secret_key="test").authenticate(request) is True


async def test_authenticate_refreshes_permissions_granted_since_login(
    admin_db: None, db_session: AsyncSession, test_user: dict
):
    await upsert_role(db_session, None, "platform-admins", "", [PERM_PLATFORM_ADMIN, "flags.read"])
    await assign_role(db_session, None, test_user["id"], "platform-admins")
    request = SessionRequest({"admin_authenticated": True, "user_id": test_user["id"], "permissions": []})

    assert await AdminAuth(secret_key="test").authenticate(request) is True
    assert request.session["permissions"] == sorted(["flags.read", PERM_PLATFORM_ADMIN])


async def test_authenticate_drops_a_session_whose_permission_was_revoked(
    admin_db: None, db_session: AsyncSession, test_user: dict
):
    """The stale session snapshot is what the views gate on, so it must not survive the revocation."""
    request = SessionRequest({"admin_authenticated": True, "user_id": test_user["id"], "permissions": [PERM_PLATFORM_ADMIN]})

    assert await AdminAuth(secret_key="test").authenticate(request) is False
    assert request.session == {}


async def test_authenticate_drops_a_session_whose_user_was_deleted(admin_db: None, db_session: AsyncSession, test_user: dict):
    await upsert_role(db_session, None, "platform-admins", "", [PERM_PLATFORM_ADMIN])
    await assign_role(db_session, None, test_user["id"], "platform-admins")
    owner = await db_session.get(User, test_user["id"])
    owner.is_deleted = True
    await db_session.commit()
    request = SessionRequest({"admin_authenticated": True, "user_id": test_user["id"], "permissions": [PERM_PLATFORM_ADMIN]})

    assert await AdminAuth(secret_key="test").authenticate(request) is False
    assert request.session == {}
