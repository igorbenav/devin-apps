"""SQLAdmin writes leave an audit trail, and admin access is re-checked per request."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.interfaces.admin.views.platform import RoleAdmin, UserRoleAdmin
from src.interfaces.admin.views.tiers import TierAdmin
from src.interfaces.admin.views.users import UserAdmin
from src.modules.platform import admin as platform_admin
from src.modules.platform.admin import AuditedAdminView, snapshot
from src.modules.platform.models import Role
from src.modules.platform.service import list_audit_events
from src.modules.tools.flags.admin import FlagAdmin
from src.modules.user.models import User

pytestmark = pytest.mark.asyncio

WRITABLE_ADMIN_VIEWS = [RoleAdmin, UserRoleAdmin, UserAdmin, TierAdmin, FlagAdmin]


def fake_request(user_id: int | None) -> Request:
    """A real request object: the mixin carries the before-state on the request scope."""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin",
            "headers": [],
            "session": {"user_id": user_id},
            "state": {},
        }
    )


@pytest.fixture
def admin_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """Point the mixin's own session at the test session; its commit is the test's."""

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(platform_admin, "local_session", session_factory)


def test_every_writable_admin_view_is_audited() -> None:
    """A writable view without the mixin writes to the database with no trace in the audit log."""
    for view in WRITABLE_ADMIN_VIEWS:
        assert issubclass(view, AuditedAdminView), f"{view.__name__} can write but is not audited"


def test_snapshot_leaves_out_credential_columns(test_user: dict) -> None:
    user = User(name="a", username="b", email="c@d.e", hashed_password="secret-hash")

    captured = snapshot(user)

    assert "hashed_password" not in captured
    assert captured["username"] == "b"


async def test_edit_records_before_and_after(db_session: AsyncSession, admin_session: None, test_user: dict) -> None:
    role = Role(name="analyst", description="before", permissions=["flags.read"])
    db_session.add(role)
    await db_session.commit()

    view = RoleAdmin()
    request = fake_request(test_user["id"])
    await view.on_model_change({}, role, False, request)
    role.description = "after"
    await db_session.commit()
    await view.after_model_change({}, role, False, request)

    event = (await list_audit_events(db_session))[0]
    assert event.action == "admin.platform_role.updated"
    assert event.actor_user_id == test_user["id"]
    assert event.before["description"] == "before"
    assert event.after["description"] == "after"
    assert event.entity_id == str(role.id)


async def test_create_records_only_an_after(db_session: AsyncSession, admin_session: None, test_user: dict) -> None:
    role = Role(name="reviewer", description="new", permissions=["kyc.approve"])

    view = RoleAdmin()
    request = fake_request(test_user["id"])
    await view.on_model_change({}, None, True, request)
    db_session.add(role)
    await db_session.commit()
    await view.after_model_change({}, role, True, request)

    event = (await list_audit_events(db_session))[0]
    assert event.action == "admin.platform_role.created"
    assert event.before is None
    assert event.after["name"] == "reviewer"


async def test_delete_records_the_row_that_went_away(db_session: AsyncSession, admin_session: None, test_user: dict) -> None:
    role = Role(name="temp", description="temp", permissions=[])
    db_session.add(role)
    await db_session.commit()
    role_id = role.id

    view = RoleAdmin()
    request = fake_request(test_user["id"])
    await view.on_model_delete(role, request)
    await db_session.delete(role)
    await db_session.commit()
    await view.after_model_delete(role, request)

    event = (await list_audit_events(db_session))[0]
    assert event.action == "admin.platform_role.deleted"
    assert event.after is None
    assert event.before["name"] == "temp"
    assert event.entity_id == str(role_id)


async def test_break_glass_admin_is_recorded_without_an_actor(db_session: AsyncSession, admin_session: None) -> None:
    """The configured break-glass login has no platform user; the event still has to exist."""
    role = Role(name="ops", description="ops", permissions=[])
    db_session.add(role)
    await db_session.commit()

    view = RoleAdmin()
    request = fake_request(user_id=None)
    await view.on_model_change({}, role, False, request)
    await view.after_model_change({}, role, False, request)

    event = (await list_audit_events(db_session))[0]
    assert event.actor_user_id is None
    assert event.action == "admin.platform_role.updated"
