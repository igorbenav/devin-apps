"""Unit tests for the KYC Review Queue: one per rule the service enforces."""

from typing import Any

import pytest
from crudauth.exceptions import ForbiddenException
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.common.exceptions import ValidationError
from src.modules.platform.constants import (
    ANALYST_PERMISSIONS,
    PERM_KYC_APPROVE,
    PERM_KYC_ESCALATE,
    PERM_KYC_REVIEW,
    REVIEWER_PERMISSIONS,
)
from src.modules.platform.crud import crud_audit_events
from src.modules.platform.dependencies import ViewerContext, require_page_permission
from src.modules.tools.kyc import service
from src.modules.tools.kyc.crud import crud_kyc_cases
from src.modules.tools.kyc.models import (
    STATE_APPROVED,
    STATE_ESCALATED,
    STATE_IN_REVIEW,
    STATE_PENDING,
    STATE_REJECTED,
)
from src.modules.tools.kyc.schemas import KycCaseCreate, KycCaseRead

pytestmark = pytest.mark.asyncio

ANALYST = set(ANALYST_PERMISSIONS)
REVIEWER = set(REVIEWER_PERMISSIONS)
REASON = "Documents verified against the company registry"


def viewer_with(permissions: set[str], user: dict[str, Any] | None = None) -> ViewerContext:
    return ViewerContext(user=user or {"id": 1, "is_superuser": False}, roles=[], permissions=permissions)


async def make_case(db: AsyncSession, state: str = STATE_PENDING, assigned_to: int | None = None) -> dict[str, Any]:
    case = await crud_kyc_cases.create(
        db=db,
        object=KycCaseCreate(
            customer_ref=f"CUS-{id(object()) % 100000}",
            customer_name="Test Customer",
            risk_score=50,
            state=state,
            assigned_to=assigned_to,
        ),
        commit=True,
        schema_to_select=KycCaseRead,
    )
    return dict(case)


async def actions_for(db: AsyncSession, case_id: int) -> list[str]:
    events = await crud_audit_events.get_multi(db=db, entity_type=service.ENTITY_TYPE, entity_id=str(case_id))
    return [event["action"] for event in events["data"]]


async def test_claim_takes_a_pending_case_into_review(db_session: AsyncSession, test_user: dict) -> None:
    case = await make_case(db_session)

    claimed = await service.claim_case(db_session, test_user, ANALYST, case["id"])

    assert claimed["state"] == STATE_IN_REVIEW
    assert claimed["assigned_to"] == test_user["id"]
    assert "kyc.case.claimed" in await actions_for(db_session, case["id"])


async def test_claim_requires_the_review_permission(db_session: AsyncSession, test_user: dict) -> None:
    case = await make_case(db_session)

    with pytest.raises(ForbiddenException, match=PERM_KYC_REVIEW):
        await service.claim_case(db_session, test_user, set(), case["id"])


async def test_claim_rejects_a_case_assigned_to_someone_else(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    case = await make_case(db_session, assigned_to=test_user_2["id"])

    with pytest.raises(ValidationError, match="already assigned"):
        await service.claim_case(db_session, test_user, ANALYST, case["id"])


async def test_release_returns_the_case_to_the_queue(db_session: AsyncSession, test_user: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user["id"])

    released = await service.release_case(db_session, test_user, ANALYST, case["id"])

    assert released["state"] == STATE_PENDING
    assert released["assigned_to"] is None
    assert "kyc.case.released" in await actions_for(db_session, case["id"])


async def test_release_is_refused_to_a_non_assignee_without_approve(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    with pytest.raises(ForbiddenException, match=PERM_KYC_APPROVE):
        await service.release_case(db_session, test_user, ANALYST, case["id"])


async def test_release_is_allowed_to_an_approver_who_is_not_the_assignee(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    released = await service.release_case(db_session, test_user, REVIEWER, case["id"])

    assert released["state"] == STATE_PENDING


async def test_approve_records_the_decision_and_its_audit_event(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    approved = await service.approve_case(db_session, test_user, REVIEWER, case["id"], REASON)

    assert approved["state"] == STATE_APPROVED
    assert approved["decided_by"] == test_user["id"]
    assert approved["decision_reason"] == REASON

    events = await crud_audit_events.get_multi(db=db_session, entity_type=service.ENTITY_TYPE, entity_id=str(case["id"]))
    decision = next(event for event in events["data"] if event["action"] == f"kyc.case.{STATE_APPROVED}")
    assert decision["before"]["state"] == STATE_IN_REVIEW
    assert decision["after"]["state"] == STATE_APPROVED
    assert decision["after"]["reason"] == REASON


async def test_analyst_cannot_approve(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    with pytest.raises(ForbiddenException, match=PERM_KYC_APPROVE):
        await service.approve_case(db_session, test_user, ANALYST, case["id"], REASON)

    assert (await service.get_case(db_session, case["id"]))["state"] == STATE_IN_REVIEW


async def test_maker_checker_blocks_the_assignee_from_deciding(db_session: AsyncSession, test_user: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user["id"])

    with pytest.raises(ForbiddenException, match="Maker/checker"):
        await service.approve_case(db_session, test_user, REVIEWER, case["id"], REASON)

    assert (await service.get_case(db_session, case["id"]))["state"] == STATE_IN_REVIEW


async def test_decision_requires_a_reason_of_ten_characters(
    db_session: AsyncSession, test_user: dict, test_user_2: dict
) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    with pytest.raises(ValidationError, match="at least 10"):
        await service.approve_case(db_session, test_user, REVIEWER, case["id"], "too short")


async def test_decision_reason_is_capped(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    with pytest.raises(ValidationError, match="at most"):
        await service.approve_case(db_session, test_user, REVIEWER, case["id"], "x" * 5000)


async def test_reject_moves_the_case_to_rejected(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user_2["id"])

    rejected = await service.reject_case(db_session, test_user, REVIEWER, case["id"], REASON)

    assert rejected["state"] == STATE_REJECTED
    assert f"kyc.case.{STATE_REJECTED}" in await actions_for(db_session, case["id"])


async def test_decisions_are_only_possible_from_in_review(db_session: AsyncSession, test_user: dict, test_user_2: dict) -> None:
    case = await make_case(db_session, state=STATE_PENDING, assigned_to=test_user_2["id"])

    with pytest.raises(ValidationError, match="expected in_review"):
        await service.approve_case(db_session, test_user, REVIEWER, case["id"], REASON)


async def test_escalate_requires_its_own_permission(db_session: AsyncSession, test_user: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user["id"])

    with pytest.raises(ForbiddenException, match=PERM_KYC_ESCALATE):
        await service.escalate_case(db_session, test_user, ANALYST, case["id"], REASON)


async def test_escalate_and_resume_round_trip(db_session: AsyncSession, test_user: dict) -> None:
    case = await make_case(db_session, state=STATE_IN_REVIEW, assigned_to=test_user["id"])

    escalated = await service.escalate_case(db_session, test_user, REVIEWER, case["id"], REASON)
    assert escalated["state"] == STATE_ESCALATED

    resumed = await service.resume_case(db_session, test_user, REVIEWER, case["id"])
    assert resumed["state"] == STATE_IN_REVIEW

    actions = await actions_for(db_session, case["id"])
    assert "kyc.case.escalated" in actions
    assert "kyc.case.resumed" in actions


async def test_allowed_actions_hides_decisions_from_the_assignee(test_user: dict) -> None:
    case = {"id": 1, "state": STATE_IN_REVIEW, "assigned_to": test_user["id"]}

    actions = service.allowed_actions(case, test_user, REVIEWER)

    assert "approve" not in actions
    assert "reject" not in actions
    assert "release" in actions


async def test_page_permission_rejects_a_user_without_kyc_review() -> None:
    dependency = require_page_permission(PERM_KYC_REVIEW)

    with pytest.raises(ForbiddenException, match=PERM_KYC_REVIEW):
        await dependency(viewer=viewer_with(set()))

    viewer = viewer_with({PERM_KYC_REVIEW})
    assert await dependency(viewer=viewer) is viewer
