"""The audit log: what ``record`` writes, and that nothing can rewrite it."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.request_context import RequestContext, set_request_context
from src.modules.platform import audit
from src.modules.platform.crud import crud_audit_events
from src.modules.platform.models import AuditEvent
from src.modules.platform.service import list_audit_entity_types, list_audit_events

pytestmark = pytest.mark.asyncio

MUTATING_METHODS = ["update", "upsert", "upsert_multi", "delete", "db_delete"]


async def test_record_writes_the_full_event(db_session: AsyncSession, test_user: dict) -> None:
    set_request_context(RequestContext(request_id="req-1", ip="10.0.0.1"))
    try:
        await audit.record(
            db_session,
            test_user,
            "kyc.case.approved",
            "kyc_case",
            42,
            before={"status": "pending"},
            after={"status": "approved"},
        )
        await db_session.commit()
    finally:
        set_request_context(None)

    events = await list_audit_events(db_session)
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_id == test_user["id"]
    assert event.action == "kyc.case.approved"
    assert event.entity_type == "kyc_case"
    assert event.entity_id == "42"
    assert event.before == {"status": "pending"}
    assert event.after == {"status": "approved"}
    assert event.request_id == "req-1"
    assert event.ip == "10.0.0.1"
    assert event.occurred_at is not None


async def test_record_accepts_a_raw_actor_id_and_a_system_actor(db_session: AsyncSession, test_user: dict) -> None:
    await audit.record(db_session, test_user["id"], "tool.thing.done", "thing", 1)
    await audit.record(db_session, None, "tool.thing.done", "thing", 2)
    await db_session.commit()

    events = await list_audit_events(db_session)
    assert {event.actor_user_id for event in events} == {test_user["id"], None}


async def test_record_rolls_back_with_the_change_it_describes(db_session: AsyncSession, test_user: dict) -> None:
    await audit.record(db_session, test_user, "tool.thing.done", "thing", 1)
    await db_session.rollback()

    assert await list_audit_events(db_session) == []


async def test_list_events_filters_by_entity_type(db_session: AsyncSession) -> None:
    await audit.record(db_session, None, "a.created", "alpha", 1)
    await audit.record(db_session, None, "b.created", "beta", 2)
    await db_session.commit()

    assert [event.entity_type for event in await list_audit_events(db_session, entity_type="alpha")] == ["alpha"]
    assert await list_audit_entity_types(db_session) == ["alpha", "beta"]


@pytest.mark.parametrize("method", MUTATING_METHODS)
async def test_audit_crud_exposes_no_update_or_delete_path(db_session: AsyncSession, method: str) -> None:
    with pytest.raises(NotImplementedError, match="append-only"):
        await getattr(crud_audit_events, method)(db=db_session, id=1)


async def test_audit_crud_can_still_create_and_read(db_session: AsyncSession) -> None:
    await audit.record(db_session, None, "tool.thing.done", "thing", 7)
    await db_session.commit()

    assert await crud_audit_events.count(db=db_session, entity_type="thing") == 1


def test_audit_model_defines_no_mutating_helpers() -> None:
    assert not {name for name in vars(AuditEvent) if name.startswith(("update", "delete"))}
