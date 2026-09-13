"""Permission resolution and the dependencies that gate routes on it."""

import pytest
from crudauth.exceptions import ForbiddenException
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.platform import service
from src.modules.platform.constants import (
    ROLE_ANALYST,
    ROLE_REVIEWER,
    permission_names,
    seeded_roles,
)
from src.modules.platform.dependencies import (
    LoginRequiredError,
    ViewerContext,
    get_current_permissions,
    get_viewer,
    require_page_permission,
    require_permission,
)

pytestmark = pytest.mark.asyncio

# Two tool permissions used as stand-ins: the platform knows nothing about them beyond what a tool declared.
PERM_KYC_REVIEW = "kyc.review"
PERM_KYC_APPROVE = "kyc.approve"

ANALYST_PERMISSIONS = seeded_roles()[ROLE_ANALYST][1]
REVIEWER_PERMISSIONS = seeded_roles()[ROLE_REVIEWER][1]


async def seed_roles(db: AsyncSession) -> None:
    for name, (description, permissions) in seeded_roles().items():
        await service.upsert_role(db, None, name, description, list(permissions))


async def test_permissions_come_from_assigned_roles(db_session: AsyncSession, test_user: dict) -> None:
    await seed_roles(db_session)
    await service.assign_role(db_session, None, test_user["id"], ROLE_ANALYST)

    permissions = await service.get_permissions_for_user(db_session, test_user["id"])

    assert permissions == set(ANALYST_PERMISSIONS)
    assert PERM_KYC_APPROVE not in permissions


async def test_multiple_roles_union_their_permissions(db_session: AsyncSession, test_user: dict) -> None:
    await seed_roles(db_session)
    await service.assign_role(db_session, None, test_user["id"], ROLE_ANALYST)
    await service.assign_role(db_session, None, test_user["id"], ROLE_REVIEWER)

    permissions = await service.get_permissions_for_user(db_session, test_user["id"])

    assert permissions == set(ANALYST_PERMISSIONS) | set(REVIEWER_PERMISSIONS)


async def test_user_without_roles_holds_nothing(db_session: AsyncSession, test_user: dict) -> None:
    assert await service.get_permissions_for_user(db_session, test_user["id"]) == set()


async def test_superuser_holds_every_permission(db_session: AsyncSession, test_user: dict) -> None:
    permissions = await service.get_permissions_for_user(db_session, test_user["id"], is_superuser=True)

    assert permissions == set(permission_names())


async def test_current_permissions_dependency_resolves_roles(db_session: AsyncSession, test_user: dict) -> None:
    await seed_roles(db_session)
    await service.assign_role(db_session, None, test_user["id"], ROLE_REVIEWER)

    permissions = await get_current_permissions(user={"id": test_user["id"]}, db=db_session)

    assert permissions == set(REVIEWER_PERMISSIONS)


async def test_require_permission_allows_holder() -> None:
    dependency = require_permission(PERM_KYC_APPROVE)
    user = {"id": 1, "is_superuser": False}

    assert await dependency(user=user, permissions={PERM_KYC_APPROVE}) is user


async def test_require_permission_rejects_non_holder_with_a_clear_message() -> None:
    dependency = require_permission(PERM_KYC_APPROVE)

    with pytest.raises(ForbiddenException, match=f"requires the '{PERM_KYC_APPROVE}' permission"):
        await dependency(user={"id": 1, "is_superuser": False}, permissions={PERM_KYC_REVIEW})


async def test_require_permission_lets_superusers_through(db_session: AsyncSession, test_user: dict) -> None:
    permissions = await get_current_permissions(user={"id": test_user["id"], "is_superuser": True}, db=db_session)
    dependency = require_permission(PERM_KYC_APPROVE)

    assert await dependency(user=test_user, permissions=permissions) == test_user


async def test_require_page_permission_rejects_non_holder() -> None:
    dependency = require_page_permission(PERM_KYC_APPROVE)
    viewer = ViewerContext(user={"id": 1}, roles=[], permissions={PERM_KYC_REVIEW})

    with pytest.raises(ForbiddenException, match=PERM_KYC_APPROVE):
        await dependency(viewer=viewer)


async def test_get_viewer_requires_a_session(db_session: AsyncSession) -> None:
    with pytest.raises(LoginRequiredError):
        await get_viewer(db=db_session, user=None)


async def test_get_viewer_exposes_roles_and_permissions(db_session: AsyncSession, test_user: dict) -> None:
    await seed_roles(db_session)
    await service.assign_role(db_session, None, test_user["id"], ROLE_ANALYST)

    viewer = await get_viewer(db=db_session, user=test_user)

    assert viewer.roles == [ROLE_ANALYST]
    assert viewer.can(PERM_KYC_REVIEW)
    assert not viewer.can(PERM_KYC_APPROVE)
