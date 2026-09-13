"""State changes for the Tool Requests tool.

Every function that writes lives here (routes never write), and every one of them records an audit event in the same
transaction as the change. Dispatching to the Devin API spends money, so submission is rate limited per requester and
the brief is always persisted before the call is attempted — a failed dispatch leaves a request that can be retried.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform_sdk import ResourceNotFoundError, ValidationError, audit, usernames_for_ids
from . import devin
from .crud import crud_tool_requests
from .models import STATUS_DISPATCHED, STATUS_FAILED, STATUS_QUEUED, ToolRequest
from .prompt import build_prompt
from .schemas import ToolRequestBrief, ToolRequestCreate, ToolRequestDispatch, ToolRequestRead

ENTITY_TYPE = "tool_request"

#: A submission starts a paid session, so one requester cannot spend the budget in an afternoon by holding the enter
#: key. Deliberately generous for a demo; tighten before this is real.
MAX_REQUESTS_PER_DAY = 5


async def list_requests(db: AsyncSession, requester_user_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Requests, newest first; scoped to one requester when given."""
    filters: dict[str, Any] = {"requester_user_id": requester_user_id} if requester_user_id is not None else {}
    result = await crud_tool_requests.get_multi(
        db=db, limit=limit, schema_to_select=ToolRequestRead, sort_columns="id", sort_orders="desc", **filters
    )
    return list(result["data"])


async def get_request(db: AsyncSession, request_id: int) -> dict[str, Any]:
    """One request, or :class:`ResourceNotFoundError`."""
    found = await crud_tool_requests.get(db=db, id=request_id, schema_to_select=ToolRequestRead)
    if found is None:
        raise ResourceNotFoundError(f"Tool request {request_id} not found")
    return dict(found)


async def _requests_today(db: AsyncSession, requester_user_id: int) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    statement = (
        select(func.count())
        .select_from(ToolRequest)
        .where(ToolRequest.requester_user_id == requester_user_id, ToolRequest.created_at >= since)
    )
    return int((await db.execute(statement)).scalar_one())


async def submit_request(db: AsyncSession, actor: dict[str, Any], brief: ToolRequestBrief) -> dict[str, Any]:
    """Record a brief and start a Devin session from it.

    The brief is committed first: if the API call fails the request survives as ``failed`` with the reason, and
    :func:`dispatch_request` can retry it without the requester retyping anything.
    """
    actor_id = int(actor["id"])
    if await _requests_today(db, actor_id) >= MAX_REQUESTS_PER_DAY:
        raise ValidationError(
            f"You have submitted {MAX_REQUESTS_PER_DAY} requests in the last 24 hours. "
            "Each one starts a paid Devin session, so the rest of today needs an admin."
        )

    created = await crud_tool_requests.create(
        db=db,
        object=ToolRequestCreate(**brief.model_dump(), requester_user_id=actor_id),
        commit=False,
        schema_to_select=ToolRequestRead,
    )
    await audit.record(
        db,
        actor,
        "intake.request.submitted",
        ENTITY_TYPE,
        created["id"],
        after={"title": created["title"], "slug_hint": created["slug_hint"], "status": STATUS_QUEUED},
    )
    await db.commit()

    return await dispatch_request(db, actor, int(created["id"]))


async def dispatch_request(db: AsyncSession, actor: dict[str, Any], request_id: int) -> dict[str, Any]:
    """Start (or retry) the Devin session for a stored request.

    A deployment with no API key leaves the request ``queued``: the page then shows the prompt to copy, which is the
    honest behaviour for a demo and for anyone who would rather start the session themselves.
    """
    stored = await get_request(db, request_id)
    if stored["status"] == STATUS_DISPATCHED:
        raise ValidationError(f"Request {request_id} already has a session")

    requester_id = int(stored["requester_user_id"])
    usernames = await usernames_for_ids(db, {requester_id})
    prompt = build_prompt(stored, usernames.get(requester_id, str(requester_id)))
    try:
        session = await devin.create_session(
            prompt,
            tags=[f"tool:{stored['slug_hint']}", "source:intake"],
            title=f"Add internal tool: {stored['title']}",
        )
    except devin.DevinNotConfigured:
        return stored
    except devin.DevinDispatchError as exc:
        return await _record_dispatch(db, actor, stored, ToolRequestDispatch(status=STATUS_FAILED, dispatch_error=str(exc)))

    return await _record_dispatch(
        db,
        actor,
        stored,
        ToolRequestDispatch(
            status=STATUS_DISPATCHED,
            session_id=session["session_id"],
            session_url=session["url"] or None,
            dispatch_error=None,
        ),
    )


async def _record_dispatch(
    db: AsyncSession, actor: dict[str, Any], stored: dict[str, Any], outcome: ToolRequestDispatch
) -> dict[str, Any]:
    await crud_tool_requests.update(db=db, object=outcome, id=stored["id"], commit=False)
    await audit.record(
        db,
        actor,
        "intake.request.dispatched" if outcome.status == STATUS_DISPATCHED else "intake.request.dispatch_failed",
        ENTITY_TYPE,
        stored["id"],
        before={"status": stored["status"]},
        after={"status": outcome.status, "session_id": outcome.session_id, "error": outcome.dispatch_error},
    )
    await db.commit()
    return await get_request(db, int(stored["id"]))
