"""State changes for the KYC Review Queue tool.

Every function that writes lives here (routes never write), and every one of them records an audit event in the same
transaction as the change.

The rules — who may claim, release, decide or escalate a case — are enforced here rather than in the router, so they
hold for any caller: a route, the seed script, or a future background job.
"""

from typing import Any

from crudauth.exceptions import ForbiddenException
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform_sdk import ResourceNotFoundError, ValidationError, audit, usernames_for_ids
from .crud import crud_kyc_cases, crud_kyc_documents
from .models import (
    STATE_APPROVED,
    STATE_ESCALATED,
    STATE_IN_REVIEW,
    STATE_PENDING,
    STATE_REJECTED,
)
from .permissions import PERM_KYC_APPROVE, PERM_KYC_ESCALATE, PERM_KYC_REVIEW
from .schemas import REASON_MAX_LENGTH, REASON_MIN_LENGTH, KycCaseRead, KycCaseUpdate, KycDocumentRead

ENTITY_TYPE = "kyc_case"

TAB_PENDING = "pending"
TAB_IN_REVIEW = "in_review"
TAB_MINE = "mine"
TAB_DECIDED = "decided"
TABS: tuple[tuple[str, str], ...] = (
    (TAB_PENDING, "Pending"),
    (TAB_IN_REVIEW, "In review"),
    (TAB_MINE, "Mine"),
    (TAB_DECIDED, "Decided"),
)


def _actor_id(actor: dict[str, Any]) -> int:
    return int(actor["id"])


def _require(permissions: set[str], permission: str, action: str) -> None:
    if permission not in permissions:
        raise ForbiddenException(f"You need the '{permission}' permission to {action}")


def _require_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if len(cleaned) < REASON_MIN_LENGTH:
        raise ValidationError(f"A reason of at least {REASON_MIN_LENGTH} characters is required")
    if len(cleaned) > REASON_MAX_LENGTH:
        raise ValidationError(f"A reason may be at most {REASON_MAX_LENGTH} characters")
    return cleaned


def _require_state(case: dict[str, Any], *expected: str) -> None:
    if case["state"] not in expected:
        raise ValidationError(f"Case {case['id']} is {case['state']}, expected {' or '.join(expected)}")


async def get_case(db: AsyncSession, case_id: int) -> dict[str, Any]:
    """One case, or :class:`ResourceNotFoundError`."""
    case = await crud_kyc_cases.get(db=db, id=case_id, schema_to_select=KycCaseRead)
    if case is None:
        raise ResourceNotFoundError(f"KYC case {case_id} not found")
    return dict(case)


async def usernames_for(db: AsyncSession, cases: list[dict[str, Any]]) -> dict[int, str]:
    """Map the user ids referenced by these cases to usernames, for display."""
    ids = {case[field] for case in cases for field in ("assigned_to", "decided_by") if case[field] is not None}
    return await usernames_for_ids(db, ids)


async def list_documents(db: AsyncSession, case_id: int) -> list[dict[str, Any]]:
    """The documents attached to a case."""
    result = await crud_kyc_documents.get_multi(
        db=db,
        case_id=case_id,
        schema_to_select=KycDocumentRead,
        sort_columns="id",
    )
    return list(result["data"])


async def list_cases(db: AsyncSession, tab: str, actor: dict[str, Any], limit: int = 200) -> list[dict[str, Any]]:
    """The queue for one tab, worst risk first, then oldest submission."""
    filters: dict[str, Any] = {}
    if tab == TAB_PENDING:
        filters["state"] = STATE_PENDING
    elif tab == TAB_IN_REVIEW:
        filters["state"] = STATE_IN_REVIEW
    elif tab == TAB_MINE:
        filters["assigned_to"] = _actor_id(actor)
    elif tab == TAB_DECIDED:
        filters["state__in"] = [STATE_APPROVED, STATE_REJECTED]
    else:
        raise ValidationError(f"Unknown queue tab '{tab}'")

    result = await crud_kyc_cases.get_multi(
        db=db,
        limit=limit,
        schema_to_select=KycCaseRead,
        sort_columns=["risk_score", "submitted_at"],
        sort_orders=["desc", "asc"],
        **filters,
    )
    return list(result["data"])


async def _apply(
    db: AsyncSession,
    actor: dict[str, Any],
    case: dict[str, Any],
    action: str,
    changes: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    """Write one transition, audit it with before/after, commit both together."""
    before = {
        "state": case["state"],
        "assigned_to": case["assigned_to"],
    }
    after = {**before, **changes}
    if reason is not None:
        after["reason"] = reason

    await crud_kyc_cases.update(db=db, object=KycCaseUpdate(**changes), id=case["id"], commit=False)
    await audit.record(db, actor, action, ENTITY_TYPE, case["id"], before=before, after=after)
    await db.commit()

    return await get_case(db, case["id"])


async def claim_case(db: AsyncSession, actor: dict[str, Any], permissions: set[str], case_id: int) -> dict[str, Any]:
    """``pending`` → ``in_review``, assigned to the actor."""
    _require(permissions, PERM_KYC_REVIEW, "claim a case")
    case = await get_case(db, case_id)
    _require_state(case, STATE_PENDING)

    assignee = case["assigned_to"]
    if assignee is not None and assignee != _actor_id(actor):
        raise ValidationError(f"Case {case_id} is already assigned to user {assignee}")

    return await _apply(
        db,
        actor,
        case,
        "kyc.case.claimed",
        {"state": STATE_IN_REVIEW, "assigned_to": _actor_id(actor)},
    )


async def release_case(db: AsyncSession, actor: dict[str, Any], permissions: set[str], case_id: int) -> dict[str, Any]:
    """``in_review`` → ``pending``, unassigned.

    The assignee, or anyone who can approve.
    """
    _require(permissions, PERM_KYC_REVIEW, "release a case")
    case = await get_case(db, case_id)
    _require_state(case, STATE_IN_REVIEW)

    is_assignee = case["assigned_to"] == _actor_id(actor)
    if not is_assignee and PERM_KYC_APPROVE not in permissions:
        raise ForbiddenException(
            f"Case {case_id} is assigned to someone else; only the assignee or a user with '{PERM_KYC_APPROVE}' can release it"
        )

    return await _apply(db, actor, case, "kyc.case.released", {"state": STATE_PENDING, "assigned_to": None})


async def _decide(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    case_id: int,
    new_state: str,
    reason: str | None,
) -> dict[str, Any]:
    _require(permissions, PERM_KYC_APPROVE, f"{'approve' if new_state == STATE_APPROVED else 'reject'} a case")
    cleaned = _require_reason(reason)
    case = await get_case(db, case_id)
    _require_state(case, STATE_IN_REVIEW)

    if case["assigned_to"] == _actor_id(actor):
        raise ForbiddenException(
            "Maker/checker: you are the reviewer assigned to this case, so you cannot decide it. "
            "Release it, or have a second reviewer decide."
        )

    return await _apply(
        db,
        actor,
        case,
        f"kyc.case.{new_state}",
        {"state": new_state, "decided_by": _actor_id(actor), "decision_reason": cleaned},
        reason=cleaned,
    )


async def approve_case(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    case_id: int,
    reason: str | None,
) -> dict[str, Any]:
    """``in_review`` → ``approved``, by someone other than the assignee."""
    return await _decide(db, actor, permissions, case_id, STATE_APPROVED, reason)


async def reject_case(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    case_id: int,
    reason: str | None,
) -> dict[str, Any]:
    """``in_review`` → ``rejected``, by someone other than the assignee."""
    return await _decide(db, actor, permissions, case_id, STATE_REJECTED, reason)


async def escalate_case(
    db: AsyncSession,
    actor: dict[str, Any],
    permissions: set[str],
    case_id: int,
    reason: str | None,
) -> dict[str, Any]:
    """``in_review`` → ``escalated``."""
    _require(permissions, PERM_KYC_ESCALATE, "escalate a case")
    cleaned = _require_reason(reason)
    case = await get_case(db, case_id)
    _require_state(case, STATE_IN_REVIEW)

    return await _apply(
        db,
        actor,
        case,
        "kyc.case.escalated",
        {"state": STATE_ESCALATED, "decision_reason": cleaned},
        reason=cleaned,
    )


async def resume_case(db: AsyncSession, actor: dict[str, Any], permissions: set[str], case_id: int) -> dict[str, Any]:
    """``escalated`` → ``in_review``, back with a reviewer."""
    _require(permissions, PERM_KYC_APPROVE, "take an escalated case back into review")
    case = await get_case(db, case_id)
    _require_state(case, STATE_ESCALATED)

    return await _apply(
        db,
        actor,
        case,
        "kyc.case.resumed",
        {"state": STATE_IN_REVIEW, "assigned_to": _actor_id(actor)},
    )


def allowed_actions(case: dict[str, Any], actor: dict[str, Any], permissions: set[str]) -> set[str]:
    """Which buttons the detail page and row partial should render.

    The same rules the service enforces, asked ahead of time. A button that is not here would 403 if it were clicked.
    """
    actions: set[str] = set()
    state = case["state"]
    is_assignee = case["assigned_to"] == _actor_id(actor)
    can_review = PERM_KYC_REVIEW in permissions
    can_approve = PERM_KYC_APPROVE in permissions

    if state == STATE_PENDING and can_review and case["assigned_to"] in (None, _actor_id(actor)):
        actions.add("claim")
    if state == STATE_IN_REVIEW and can_review and (is_assignee or can_approve):
        actions.add("release")
    if state == STATE_IN_REVIEW and can_approve and not is_assignee:
        actions.update({"approve", "reject"})
    if state == STATE_IN_REVIEW and PERM_KYC_ESCALATE in permissions:
        actions.add("escalate")
    if state == STATE_ESCALATED and can_approve:
        actions.add("resume")
    return actions
