"""Role and permission resolution, plus the audit-log read used by ``/audit``.

Every state change here goes through a service function that records an audit entry; route handlers never write.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import ResourceNotFoundError
from . import audit
from .constants import ALL_PERMISSIONS, AUDIT_PAGE_SIZE
from .models import AuditEvent, Role, UserRole


class RoleNotFoundError(ResourceNotFoundError):
    """Raised when a role name does not exist."""


async def get_roles_for_user(db: AsyncSession, user_id: int) -> list[Role]:
    """The roles assigned to a user, ordered by name."""
    statement = select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id).order_by(Role.name)
    result = await db.execute(statement)
    return list(result.scalars().all())


async def get_permissions_for_user(db: AsyncSession, user_id: int, *, is_superuser: bool = False) -> set[str]:
    """The flat set of permissions a user holds.

    Superusers hold every permission in the catalog, so a superuser never has to be granted roles to operate the
    platform.
    """
    if is_superuser:
        return set(ALL_PERMISSIONS)

    roles = await get_roles_for_user(db, user_id)
    return {permission for role in roles for permission in role.permissions}


async def get_role_by_name(db: AsyncSession, name: str) -> Role:
    """Load a role by name, raising :class:`RoleNotFoundError` when missing."""
    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if role is None:
        raise RoleNotFoundError(f"Role '{name}' does not exist")
    return role


async def upsert_role(
    db: AsyncSession,
    actor: audit.Actor,
    name: str,
    description: str | None,
    permissions: list[str],
) -> Role:
    """Create the role or update its description and permissions in place."""
    existing = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()

    if existing is None:
        role = Role(name=name, description=description, permissions=list(permissions))
        db.add(role)
        await db.flush()
        await audit.record(
            db, actor, "platform.role.created", "role", role.id, after={"name": name, "permissions": list(permissions)}
        )
        await db.commit()
        return role

    before = {"name": existing.name, "description": existing.description, "permissions": list(existing.permissions)}
    existing.description = description
    existing.permissions = list(permissions)
    await db.flush()
    await audit.record(
        db,
        actor,
        "platform.role.updated",
        "role",
        existing.id,
        before=before,
        after={"name": name, "description": description, "permissions": list(permissions)},
    )
    await db.commit()
    return existing


async def assign_role(db: AsyncSession, actor: audit.Actor, user_id: int, role_name: str) -> UserRole:
    """Assign a role to a user.

    Assigning an already-held role is a no-op.
    """
    role = await get_role_by_name(db, role_name)

    statement = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
    existing = (await db.execute(statement)).scalar_one_or_none()
    if existing is not None:
        return existing

    assignment = UserRole(user_id=user_id, role_id=role.id)
    db.add(assignment)
    await db.flush()
    await audit.record(
        db,
        actor,
        "platform.role.assigned",
        "user",
        user_id,
        after={"role": role.name},
    )
    await db.commit()
    return assignment


async def revoke_role(db: AsyncSession, actor: audit.Actor, user_id: int, role_name: str) -> None:
    """Remove a role from a user.

    Revoking a role the user lacks is a no-op.
    """
    role = await get_role_by_name(db, role_name)

    statement = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
    existing = (await db.execute(statement)).scalar_one_or_none()
    if existing is None:
        return

    await db.delete(existing)
    await db.flush()
    await audit.record(db, actor, "platform.role.revoked", "user", user_id, before={"role": role.name})
    await db.commit()


async def list_audit_events(
    db: AsyncSession,
    entity_type: str | None = None,
    limit: int = AUDIT_PAGE_SIZE,
) -> list[AuditEvent]:
    """The most recent audit events, newest first, optionally filtered by entity type."""
    statement = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)

    result = await db.execute(statement)
    return list(result.scalars().all())


async def list_audit_entity_types(db: AsyncSession) -> list[str]:
    """Distinct entity types present in the audit log, for the filter dropdown."""
    result = await db.execute(select(AuditEvent.entity_type).distinct().order_by(AuditEvent.entity_type))
    return list(result.scalars().all())


async def list_user_role_names(db: AsyncSession, user: dict[str, Any]) -> list[str]:
    """Role names for a user dict, used by the nav bar."""
    roles = await get_roles_for_user(db, int(user["id"]))
    return [role.name for role in roles]
