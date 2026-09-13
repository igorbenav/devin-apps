"""The audit trail every state-changing service function writes to.

``record`` is the only writer. It never commits: it flushes into the caller's
session so the audit row lands in the same transaction as the change it
describes — if the business write rolls back, so does its audit entry.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...infrastructure.request_context import get_request_context
from .crud import crud_audit_events
from .schemas import AuditEventCreate

Actor = dict[str, Any] | int | None


def _actor_id(actor: Actor) -> int | None:
    """Accept a user dict (the shape route dependencies hand around) or a raw id."""
    if actor is None:
        return None
    if isinstance(actor, int):
        return actor
    user_id = actor.get("id")
    return int(user_id) if user_id is not None else None


async def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: Any,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Append one audit event.

    Args:
        session: The session the state change is being made in.
        actor: The acting user dict or user id; ``None`` for system actions.
        action: Past-tense dotted action, e.g. ``"kyc.case.approved"``.
        entity_type: The entity the action applied to, e.g. ``"kyc_case"``.
        entity_id: Identifier of that entity (stored as a string).
        before: Serializable snapshot of the changed fields before the change.
        after: Serializable snapshot of the changed fields after the change.
    """
    context = get_request_context()

    await crud_audit_events.create(
        db=session,
        object=AuditEventCreate(
            actor_user_id=_actor_id(actor),
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before=before,
            after=after,
            request_id=context.request_id if context else None,
            ip=context.ip if context else None,
        ),
        commit=False,
    )
    await session.flush()
