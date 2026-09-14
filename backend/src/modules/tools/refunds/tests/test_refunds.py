"""Unit tests for the Refunds tool: one per rule, one per transition, one per permission gate."""

from decimal import Decimal
from typing import Any

import pytest
from crudauth.exceptions import ForbiddenException
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.common.exceptions import ValidationError
from src.modules.platform.crud import crud_audit_events
from src.modules.platform.dependencies import ViewerContext, require_page_permission
from src.modules.tools.refunds import service
from src.modules.tools.refunds.crud import crud_refund_requests
from src.modules.tools.refunds.models import (
    STATE_APPROVED,
    STATE_PROCESSED,
    STATE_REJECTED,
    STATE_REQUESTED,
)
from src.modules.tools.refunds.permissions import (
    PERM_REFUNDS_APPROVE,
    PERM_REFUNDS_PROCESS,
    PERM_REFUNDS_REQUEST,
    REQUIRED_PERMISSION,
)
from src.modules.tools.refunds.schemas import RefundRequestCreate, RefundRequestRead

pytestmark = pytest.mark.asyncio

AGENT = {REQUIRED_PERMISSION, PERM_REFUNDS_REQUEST, PERM_REFUNDS_PROCESS}
TEAM_LEAD = {*AGENT, PERM_REFUNDS_APPROVE}
REASON = "Duplicate charge confirmed in the payment provider dashboard"
REQUEST_REASON = "Customer was charged twice for the same order"


def viewer_with(permissions: set[str], user: dict[str, Any] | None = None) -> ViewerContext:
    return ViewerContext(user=user or {"id": 1, "is_superuser": False}, roles=[], permissions=permissions)


async def make_refund(
    db: AsyncSession,
    state: str = STATE_REQUESTED,
    requested_by: int | None = None,
    amount: str = "120.00",
) -> dict[str, Any]:
    unique = id(object()) % 100000
    refund = await crud_refund_requests.create(
        db=db,
        object=RefundRequestCreate(
            customer_ref=f"CUS-{unique}",
            order_ref=f"ORD-{unique}",
            amount=Decimal(amount),
            currency="EUR",
            reason=REQUEST_REASON,
            requested_by=requested_by,
            state=state,
        ),
        commit=True,
        schema_to_select=RefundRequestRead,
    )
    return dict(refund)


async def actions_for(db: AsyncSession, refund_id: int) -> list[str]:
    events = await crud_audit_events.get_multi(db=db, entity_type=service.ENTITY_TYPE, entity_id=str(refund_id))
    return [event["action"] for event in events["data"]]


# --- rules that must never be broken (brief item 5) ---------------------------------------


async def test_a_high_value_refund_is_never_approved_without_a_reason(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    refund = await make_refund(db_session, requested_by=test_user_2["id"], amount="1500.00")

    with pytest.raises(ValidationError, match="above 1,000"):
        await service.approve_refund(db_session, test_user, TEAM_LEAD, refund["id"], "")

    assert (await service.get_refund(db_session, refund["id"]))["state"] == STATE_REQUESTED


async def test_the_requester_cannot_approve_their_own_refund(db_session: AsyncSession, test_user: dict) -> None:
    refund = await make_refund(db_session, requested_by=test_user["id"])

    with pytest.raises(ForbiddenException, match="cannot decide it"):
        await service.approve_refund(db_session, test_user, TEAM_LEAD, refund["id"], REASON)

    assert (await service.get_refund(db_session, refund["id"]))["state"] == STATE_REQUESTED


async def test_a_processed_refund_never_changes_state_again(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    refund = await make_refund(db_session, state=STATE_PROCESSED, requested_by=test_user_2["id"])

    with pytest.raises(ValidationError, match="expected requested"):
        await service.approve_refund(db_session, test_user, TEAM_LEAD, refund["id"], REASON)
    with pytest.raises(ValidationError, match="expected approved"):
        await service.process_refund(db_session, test_user, AGENT, refund["id"])

    assert (await service.get_refund(db_session, refund["id"]))["state"] == STATE_PROCESSED


# --- state transitions --------------------------------------------------------------------


async def test_create_puts_a_refund_in_requested_attributed_to_the_actor(db_session: AsyncSession, test_user: dict) -> None:
    created = await service.create_refund(
        db_session,
        test_user,
        AGENT,
        RefundRequestCreate(
            customer_ref="CUS-7001",
            order_ref="ORD-7001",
            amount=Decimal("99.50"),
            currency="eur",
            reason=REQUEST_REASON,
        ),
    )

    assert created["state"] == STATE_REQUESTED
    assert created["requested_by"] == test_user["id"]
    assert created["currency"] == "EUR"
    assert "refunds.request.created" in await actions_for(db_session, created["id"])


async def test_requested_becomes_approved_with_who_when_and_why(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    refund = await make_refund(db_session, requested_by=test_user_2["id"])

    approved = await service.approve_refund(db_session, test_user, TEAM_LEAD, refund["id"], REASON)

    assert approved["state"] == STATE_APPROVED
    assert approved["decided_by"] == test_user["id"]
    assert approved["decision_reason"] == REASON
    assert approved["decided_at"] is not None

    events = await crud_audit_events.get_multi(db=db_session, entity_type=service.ENTITY_TYPE, entity_id=str(refund["id"]))
    decision = next(event for event in events["data"] if event["action"] == f"refunds.request.{STATE_APPROVED}")
    assert decision["before"]["state"] == STATE_REQUESTED
    assert decision["after"] == {"state": STATE_APPROVED, "reason": REASON}


async def test_requested_becomes_rejected(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    refund = await make_refund(db_session, requested_by=test_user_2["id"])

    rejected = await service.reject_refund(db_session, test_user, TEAM_LEAD, refund["id"], REASON)

    assert rejected["state"] == STATE_REJECTED
    assert rejected["decision_reason"] == REASON
    assert f"refunds.request.{STATE_REJECTED}" in await actions_for(db_session, refund["id"])


async def test_approved_becomes_processed(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    refund = await make_refund(db_session, state=STATE_APPROVED, requested_by=test_user_2["id"])

    processed = await service.process_refund(db_session, test_user, AGENT, refund["id"])

    assert processed["state"] == STATE_PROCESSED
    assert processed["processed_by"] == test_user["id"]
    assert processed["processed_at"] is not None
    assert "refunds.request.processed" in await actions_for(db_session, refund["id"])


async def test_rejection_is_terminal(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    refund = await make_refund(db_session, state=STATE_REJECTED, requested_by=test_user_2["id"])

    with pytest.raises(ValidationError, match="expected requested"):
        await service.approve_refund(db_session, test_user, TEAM_LEAD, refund["id"], REASON)
    with pytest.raises(ValidationError, match="expected approved"):
        await service.process_refund(db_session, test_user, AGENT, refund["id"])


async def test_a_requested_refund_cannot_skip_straight_to_processed(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    refund = await make_refund(db_session, requested_by=test_user_2["id"])

    with pytest.raises(ValidationError, match="expected approved"):
        await service.process_refund(db_session, test_user, AGENT, refund["id"])


# --- permissions --------------------------------------------------------------------------


async def test_an_agent_without_approve_cannot_approve(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    refund = await make_refund(db_session, requested_by=test_user_2["id"])

    with pytest.raises(ForbiddenException, match=PERM_REFUNDS_APPROVE):
        await service.approve_refund(db_session, test_user, AGENT, refund["id"], REASON)

    assert (await service.get_refund(db_session, refund["id"]))["state"] == STATE_REQUESTED


async def test_raising_and_processing_need_their_own_permissions(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    refund = await make_refund(db_session, state=STATE_APPROVED, requested_by=test_user_2["id"])

    with pytest.raises(ForbiddenException, match=PERM_REFUNDS_PROCESS):
        await service.process_refund(db_session, test_user, {REQUIRED_PERMISSION}, refund["id"])

    with pytest.raises(ForbiddenException, match=PERM_REFUNDS_REQUEST):
        await service.create_refund(
            db_session,
            test_user,
            {REQUIRED_PERMISSION},
            RefundRequestCreate(
                customer_ref="CUS-7002",
                order_ref="ORD-7002",
                amount=Decimal("10.00"),
                currency="EUR",
                reason=REQUEST_REASON,
            ),
        )


async def test_page_permission_rejects_a_user_without_refunds_view() -> None:
    dependency = require_page_permission(REQUIRED_PERMISSION)

    with pytest.raises(ForbiddenException, match=REQUIRED_PERMISSION):
        await dependency(viewer=viewer_with(set()))

    viewer = viewer_with({REQUIRED_PERMISSION})
    assert await dependency(viewer=viewer) is viewer


# --- what the UI is allowed to offer --------------------------------------------------------


async def test_allowed_actions_hides_the_decision_from_the_requester(test_user: dict) -> None:
    own = {"id": 1, "state": STATE_REQUESTED, "requested_by": test_user["id"]}
    someone_elses = {"id": 2, "state": STATE_REQUESTED, "requested_by": test_user["id"] + 1}

    assert service.allowed_actions(own, test_user, TEAM_LEAD) == set()
    assert service.allowed_actions(someone_elses, test_user, TEAM_LEAD) == {"approve", "reject"}


async def test_allowed_actions_offers_payout_only_on_approved_refunds(test_user: dict) -> None:
    approved = {"id": 1, "state": STATE_APPROVED, "requested_by": test_user["id"]}
    processed = {"id": 2, "state": STATE_PROCESSED, "requested_by": test_user["id"]}

    assert service.allowed_actions(approved, test_user, AGENT) == {"process"}
    assert service.allowed_actions(processed, test_user, TEAM_LEAD) == set()


async def test_the_dashboard_counts_what_is_outstanding(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    await make_refund(db_session, requested_by=test_user_2["id"])
    approved = await make_refund(db_session, state=STATE_APPROVED, requested_by=test_user_2["id"])
    await service.process_refund(db_session, test_user, AGENT, approved["id"])

    counts = await service.dashboard_counts(db_session)

    assert counts["requested"] >= 1
    assert counts["processed_this_week"] >= 1
