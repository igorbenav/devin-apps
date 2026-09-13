"""State transitions on roles and role assignments, and the audit they leave."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.platform import service
from src.modules.platform.constants import ROLE_ANALYST
from src.modules.platform.models import AuditEvent, UserRole

pytestmark = pytest.mark.asyncio

# Tool permissions used as stand-in strings: roles are just lists the platform stores.
PERM_KYC_REVIEW = "kyc.review"
PERM_FLAGS_READ = "flags.read"


async def audit_actions(db: AsyncSession) -> list[str]:
    result = await db.execute(select(AuditEvent.action).order_by(AuditEvent.id))
    return list(result.scalars().all())


async def test_upsert_role_creates_then_updates(db_session: AsyncSession) -> None:
    created = await service.upsert_role(db_session, None, ROLE_ANALYST, "Reviews cases", [PERM_KYC_REVIEW])
    updated = await service.upsert_role(db_session, None, ROLE_ANALYST, "Reviews cases", [PERM_KYC_REVIEW, PERM_FLAGS_READ])

    assert updated.id == created.id
    assert set(updated.permissions) == {PERM_KYC_REVIEW, PERM_FLAGS_READ}
    assert await audit_actions(db_session) == ["platform.role.created", "platform.role.updated"]


async def test_assign_role_is_idempotent(db_session: AsyncSession, test_user: dict) -> None:
    await service.upsert_role(db_session, None, ROLE_ANALYST, None, [PERM_KYC_REVIEW])

    first = await service.assign_role(db_session, None, test_user["id"], ROLE_ANALYST)
    second = await service.assign_role(db_session, None, test_user["id"], ROLE_ANALYST)

    assert first.id == second.id
    assignments = (await db_session.execute(select(UserRole).where(UserRole.user_id == test_user["id"]))).scalars().all()
    assert len(assignments) == 1
    assert await audit_actions(db_session) == ["platform.role.created", "platform.role.assigned"]


async def test_revoke_role_removes_assignment_and_audits(db_session: AsyncSession, test_user: dict) -> None:
    await service.upsert_role(db_session, None, ROLE_ANALYST, None, [PERM_KYC_REVIEW])
    await service.assign_role(db_session, None, test_user["id"], ROLE_ANALYST)

    await service.revoke_role(db_session, None, test_user["id"], ROLE_ANALYST)

    assert await service.get_permissions_for_user(db_session, test_user["id"]) == set()
    assert await audit_actions(db_session) == [
        "platform.role.created",
        "platform.role.assigned",
        "platform.role.revoked",
    ]


async def test_revoke_role_the_user_lacks_is_a_no_op(db_session: AsyncSession, test_user: dict) -> None:
    await service.upsert_role(db_session, None, ROLE_ANALYST, None, [PERM_KYC_REVIEW])

    await service.revoke_role(db_session, None, test_user["id"], ROLE_ANALYST)

    assert await audit_actions(db_session) == ["platform.role.created"]


async def test_assign_unknown_role_raises(db_session: AsyncSession, test_user: dict) -> None:
    with pytest.raises(service.RoleNotFoundError):
        await service.assign_role(db_session, None, test_user["id"], "nope")
