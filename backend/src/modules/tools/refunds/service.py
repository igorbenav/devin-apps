"""State changes for the Refunds tool.

Every function that writes lives here (routes never write), and every one of them records an
audit event in the same transaction as the change — that trail, per refund, is what finance and
an auditor are shown when they ask who approved what, when and why.

The four rules that must hold whatever the caller is are enforced here rather than in the
router: a refund above :data:`HIGH_VALUE_THRESHOLD` is never approved without a reason, the
person who raised a request never decides it, a processed refund never changes state again, and
rejection is terminal.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from crudauth.exceptions import ForbiddenException
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform_sdk import ResourceNotFoundError, ValidationError, audit, usernames_for_ids
from .crud import crud_refund_requests
from .models import (
    HIGH_VALUE_THRESHOLD,
    STATE_APPROVED,
    STATE_PROCESSED,
    STATE_REJECTED,
    STATE_REQUESTED,
)
from .permissions import PERM_REFUNDS_APPROVE, PERM_REFUNDS_PROCESS, PERM_REFUNDS_REQUEST
from .schemas import REASON_MAX_LENGTH, REASON_MIN_LENGTH, RefundRequestCreate, RefundRequestRead, RefundRequestUpdate

ENTITY_TYPE = "refunds_request"

FILTER_ALL = "all"
STATE_FILTERS: tuple[tuple[str, str], ...] = (
    (FILTER_ALL, "All"),
    (STATE_REQUESTED, "Requested"),
    (STATE_APPROVED, "Approved"),
    (STATE_PROCESSED, "Processed"),
    (STATE_REJECTED, "Rejected"),
)

PROCESSED_THIS_WEEK_DAYS = 7


def _actor_id(actor: dict[str, Any]) -> int:
    return int(actor["id"])


def _require(permissions: set[str], permission: str, action: str) -> None:
    if permission not in permissions:
        raise ForbiddenException(f"You need the '{permission}' permission to {action}")


def _require_decision_reason(amount: Decimal, reason: str | None) -> str:
    """Every decision carries a reason, and a high-value approval says so explicitly."""
    cleaned = (reason or "").strip()
    if len(cleaned) < REASON_MIN_LENGTH:
        if amount > HIGH_VALUE_THRESHOLD:
            raise ValidationError(
                f"A refund above {HIGH_VALUE_THRESHOLD:,.0f} cannot be decided without a reason of at least "
                f"{REASON_MIN_LENGTH} characters"
            )
        raise ValidationError(f"A reason of at least {REASON_MIN_LENGTH} characters is required")
    if len(cleaned) > REASON_MAX_LENGTH:
        raise ValidationError(f"A reason may be at most {REASON_MAX_LENGTH} characters")
    return cleaned


def _require_state(refund: dict[str, Any], *expected: str) -> None:
    if refund["state"] not in expected:
        raise ValidationError(f"Refund {refund['id']} is {refund['state']}, expected {' or '.join(expected)}")


async def get_refund(db: AsyncSession, refund_id: int) -> dict[str, Any]:
    """One refund request, or :class:`ResourceNotFoundError`."""
    refund = await crud_refund_requests.get(db=db, id=refund_id, schema_to_select=RefundRequestRead)
    if refund is None:
        raise ResourceNotFoundError(f"Refund request {refund_id} not found")
    return dict(refund)


async def usernames_for(db: AsyncSession, refunds: list[dict[str, Any]]) -> dict[int, str]:
    """Map the user ids these refunds reference to usernames, for display."""
    fields = ("requested_by", "decided_by", "processed_by")
    ids = {refund[field] for refund in refunds for field in fields if refund[field] is not None}
    return await usernames_for_ids(db, ids)


async def list_refunds(db: AsyncSession, state: str = FILTER_ALL, limit: int = 200) -> list[dict[str, Any]]:
    """The refunds in one state (or all of them), newest first."""
    if state not in {name for name, _ in STATE_FILTERS}:
        raise ValidationError(f"Unknown refund state '{state}'")

    filters: dict[str, Any] = {} if state == FILTER_ALL else {"state": state}
    result = await crud_refund_requests.get_multi(
        db=db,
        limit=limit,
        schema_to_select=RefundRequestRead,
        sort_columns="id",
        sort_orders="desc",
        **filters,
    )
    return list(result["data"])


async def dashboard_counts(db: AsyncSession) -> dict[str, int]:
    """What is waiting on a decision, what is approved but unpaid, and what went out this week."""
    since = datetime.now(UTC) - timedelta(days=PROCESSED_THIS_WEEK_DAYS)
    return {
        "requested": await crud_refund_requests.count(db=db, state=STATE_REQUESTED),
        "awaiting_payout": await crud_refund_requests.count(db=db, state=STATE_APPROVED),
        "processed_this_week": await crud_refund_requests.count(db=db, state=STATE_PROCESSED, processed_at__gte=since),
    }


async def _apply(
    db: AsyncSession,
    actor: dict[str, Any],
    refund: dict[str, Any],
    action: str,
    changes: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    """Write one transition, audit it with before/after, commit both together."""
    before = {"state": refund["state"]}
    after: dict[str, Any] = {"state": changes["state"]}
    if reason is not None:
        after["reason"] = reason

    await crud_refund_requests.update(db=db, object=RefundRequestUpdate(**changes), id=refund["id"], commit=False)
    await audit.record(db, actor, action, ENTITY_TYPE, refund["id"], before=before, after=after)
    await db.commit()

    return await get_refund(db, refund["id"])


async def create_refund(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    payload: RefundRequestCreate,
) -> dict[str, Any]:
    """Raise a refund request in the ``requested`` state, attributed to the actor."""
    _require(permissions, PERM_REFUNDS_REQUEST, "raise a refund request")

    created = await crud_refund_requests.create(
        db=db,
        object=payload.model_copy(update={"requested_by": _actor_id(actor), "state": STATE_REQUESTED}),
        commit=False,
        schema_to_select=RefundRequestRead,
    )
    await audit.record(
        db,
        actor,
        "refunds.request.created",
        ENTITY_TYPE,
        created["id"],
        after={
            "state": STATE_REQUESTED,
            "amount": str(created["amount"]),
            "currency": created["currency"],
            "order_ref": created["order_ref"],
        },
    )
    await db.commit()
    return dict(created)


async def _decide(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    refund_id: int,
    new_state: str,
    reason: str | None,
) -> dict[str, Any]:
    _require(permissions, PERM_REFUNDS_APPROVE, f"{'approve' if new_state == STATE_APPROVED else 'reject'} a refund")
    refund = await get_refund(db, refund_id)
    _require_state(refund, STATE_REQUESTED)

    if refund["requested_by"] == _actor_id(actor):
        raise ForbiddenException("You raised this refund request, so you cannot decide it. Another approver has to.")

    cleaned = _require_decision_reason(refund["amount"], reason)

    return await _apply(
        db,
        actor,
        refund,
        f"refunds.request.{new_state}",
        {
            "state": new_state,
            "decided_by": _actor_id(actor),
            "decision_reason": cleaned,
            "decided_at": datetime.now(UTC),
        },
        reason=cleaned,
    )


async def approve_refund(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    refund_id: int,
    reason: str | None,
) -> dict[str, Any]:
    """``requested`` → ``approved``, by an approver who did not raise the request."""
    return await _decide(db, actor, permissions, refund_id, STATE_APPROVED, reason)


async def reject_refund(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    refund_id: int,
    reason: str | None,
) -> dict[str, Any]:
    """``requested`` → ``rejected``, which is terminal."""
    return await _decide(db, actor, permissions, refund_id, STATE_REJECTED, reason)


async def process_refund(db: AsyncSession, actor: dict[str, Any], permissions: set[str], refund_id: int) -> dict[str, Any]:
    """``approved`` → ``processed``: the money has gone out, and nothing moves after this."""
    _require(permissions, PERM_REFUNDS_PROCESS, "mark a refund as paid out")
    refund = await get_refund(db, refund_id)
    _require_state(refund, STATE_APPROVED)

    return await _apply(
        db,
        actor,
        refund,
        "refunds.request.processed",
        {"state": STATE_PROCESSED, "processed_by": _actor_id(actor), "processed_at": datetime.now(UTC)},
    )


def allowed_actions(refund: dict[str, Any], actor: dict[str, Any], permissions: set[str]) -> set[str]:
    """Which buttons the detail page and the row partial should render.

    The same rules the service enforces, asked ahead of time: a button that is not in here would be refused if it were
    clicked anyway.
    """
    actions: set[str] = set()
    if refund["state"] == STATE_REQUESTED and PERM_REFUNDS_APPROVE in permissions:
        if refund["requested_by"] != _actor_id(actor):
            actions.update({"approve", "reject"})
    if refund["state"] == STATE_APPROVED and PERM_REFUNDS_PROCESS in permissions:
        actions.add("process")
    return actions
