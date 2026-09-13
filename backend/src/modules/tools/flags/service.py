"""State changes for the Feature Flags tool.

Every function that writes lives here (routes never write), and every one of them records an audit event in the same
transaction as the change.
"""

import hashlib
from typing import Any

from crudauth.exceptions import ForbiddenException
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...common.exceptions import ResourceExistsError, ResourceNotFoundError, ValidationError
from ...platform import audit
from ...platform.constants import PERM_FLAGS_WRITE
from .crud import crud_flags
from .models import Flag
from .schemas import FlagCreate, FlagRead, FlagUpdate

ENTITY_TYPE = "feature_flag"
LIST_LIMIT = 200


def _actor_id(actor: dict[str, Any]) -> int | None:
    raw = actor.get("id")
    return int(raw) if raw is not None else None


def _require_write(permissions: set[str]) -> None:
    if PERM_FLAGS_WRITE not in permissions:
        raise ForbiddenException(f"This action requires the '{PERM_FLAGS_WRITE}' permission")


def _readable(error: PydanticValidationError) -> str:
    """The first field error, phrased for a user looking at the form."""
    first = error.errors()[0]
    field = str(first["loc"][0]) if first["loc"] else "input"
    return f"{field}: {first['msg']}"


def _snapshot(flag: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": flag["enabled"],
        "rollout_percent": flag["rollout_percent"],
        "description": flag["description"],
    }


async def count_flags(db: AsyncSession) -> int:
    """How many flags exist, so the page can say when it is not showing all of them."""
    return int(await crud_flags.count(db=db))


async def list_flags(db: AsyncSession, limit: int = LIST_LIMIT) -> list[dict[str, Any]]:
    """Flags by key, up to ``limit``."""
    result = await crud_flags.get_multi(
        db=db,
        limit=limit,
        schema_to_select=FlagRead,
        sort_columns="key",
        sort_orders="asc",
    )
    return list(result["data"])


async def get_flag(db: AsyncSession, flag_id: int) -> dict[str, Any]:
    """One flag by id, or :class:`ResourceNotFoundError`."""
    flag = await crud_flags.get(db=db, id=flag_id, schema_to_select=FlagRead)
    if flag is None:
        raise ResourceNotFoundError(f"Flag {flag_id} not found")
    return dict(flag)


async def _lock_flag(db: AsyncSession, flag_id: int) -> dict[str, Any]:
    """Read a flag with ``SELECT ... FOR UPDATE`` so concurrent writers queue instead of clobbering each other.

    A toggle is a read-modify-write; without the lock two simultaneous toggles both read the old value, write the same
    inverse, and one of them is silently lost.
    """
    result = await db.execute(select(Flag).where(Flag.id == flag_id).with_for_update())
    flag = result.scalar_one_or_none()
    if flag is None:
        raise ResourceNotFoundError(f"Flag {flag_id} not found")
    return FlagRead.model_validate(flag, from_attributes=True).model_dump()


async def get_flag_by_key(db: AsyncSession, key: str) -> dict[str, Any]:
    """One flag by key, or :class:`ResourceNotFoundError`."""
    flag = await crud_flags.get(db=db, key=key, schema_to_select=FlagRead)
    if flag is None:
        raise ResourceNotFoundError(f"Flag '{key}' not found")
    return dict(flag)


async def create_flag(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    key: str,
    description: str = "",
    enabled: bool = False,
    rollout_percent: int = 100,
) -> dict[str, Any]:
    """Create a flag and audit it."""
    _require_write(permissions)

    if await crud_flags.exists(db=db, key=key):
        raise ResourceExistsError(f"A flag with key '{key}' already exists")

    try:
        new_flag = FlagCreate(
            key=key,
            description=description,
            enabled=enabled,
            rollout_percent=rollout_percent,
            updated_by=_actor_id(actor),
        )
    except PydanticValidationError as exc:
        raise ValidationError(_readable(exc)) from exc

    try:
        created = await crud_flags.create(
            db=db,
            object=new_flag,
            commit=False,
            schema_to_select=FlagRead,
        )
    except IntegrityError as exc:
        await db.rollback()
        raise ResourceExistsError(f"A flag with key '{key}' already exists") from exc
    await audit.record(db, actor, "flags.flag.created", ENTITY_TYPE, created["id"], after=_snapshot(dict(created)))
    await db.commit()
    return await get_flag(db, created["id"])


async def update_flag(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    flag_id: int,
    description: str | None = None,
    enabled: bool | None = None,
    rollout_percent: int | None = None,
) -> dict[str, Any]:
    """Change a flag's description, state or rollout, and audit the change."""
    _require_write(permissions)
    flag = await _lock_flag(db, flag_id)

    try:
        changes = FlagUpdate(
            description=description,
            enabled=enabled,
            rollout_percent=rollout_percent,
            updated_by=_actor_id(actor),
        )
    except PydanticValidationError as exc:
        raise ValidationError(_readable(exc)) from exc

    changed = changes.model_dump(exclude_none=True, exclude={"updated_by"})
    await crud_flags.update(
        db=db,
        object={**changed, "updated_by": _actor_id(actor)},
        id=flag_id,
        commit=False,
    )

    after = {**_snapshot(flag), **changed}
    await audit.record(db, actor, "flags.flag.updated", ENTITY_TYPE, flag_id, before=_snapshot(flag), after=after)
    await db.commit()
    return await get_flag(db, flag_id)


async def toggle_flag(db: AsyncSession, actor: dict[str, Any], permissions: set[str], flag_id: int) -> dict[str, Any]:
    """Flip a flag on or off, and audit the flip."""
    _require_write(permissions)
    flag = await _lock_flag(db, flag_id)

    await crud_flags.update(
        db=db,
        object=FlagUpdate(enabled=not flag["enabled"], updated_by=_actor_id(actor)),
        id=flag_id,
        commit=False,
    )
    await audit.record(
        db,
        actor,
        "flags.flag.toggled",
        ENTITY_TYPE,
        flag_id,
        before=_snapshot(flag),
        after={**_snapshot(flag), "enabled": not flag["enabled"]},
    )
    await db.commit()
    return await get_flag(db, flag_id)


def bucket_of(key: str, subject: str) -> int:
    """The subject's stable 0–99 bucket for this flag.

    Hashed per flag key so a subject in the first 10% of one flag is not automatically in the first 10% of every other
    flag.
    """
    digest = hashlib.sha256(f"{key}:{subject}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100


def evaluate(flag: dict[str, Any], subject: str) -> tuple[bool, str]:
    """Whether the flag is on for this subject, and why."""
    if not flag["enabled"]:
        return False, "flag disabled"
    if flag["rollout_percent"] >= 100:
        return True, "flag enabled for everyone"
    if flag["rollout_percent"] <= 0:
        return False, "rollout is 0%"

    bucket = bucket_of(flag["key"], subject)
    if bucket < flag["rollout_percent"]:
        return True, f"subject in rollout bucket {bucket} of {flag['rollout_percent']}%"
    return False, f"subject in bucket {bucket}, outside {flag['rollout_percent']}% rollout"
