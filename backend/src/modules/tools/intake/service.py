"""State changes for the Tool Requests tool.

Every function that writes lives here (routes never write), and every one of them records an audit event in the same
transaction as the change. Dispatching to the Devin API spends money, so submission is rate limited per requester and
the brief is always persisted before the call is attempted — a failed dispatch leaves a request that can be retried.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform_sdk import (
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
    audit,
    get_tool,
    usernames_for_ids,
)
from . import devin
from .crud import crud_tool_requests
from .models import (
    RETRYABLE_STATUSES,
    STATUS_DISPATCHED,
    STATUS_DISPATCHING,
    STATUS_FAILED,
    STATUS_QUEUED,
    ToolRequest,
)
from .prompt import build_prompt
from .schemas import ToolRequestBrief, ToolRequestCreate, ToolRequestDispatch, ToolRequestRead

ENTITY_TYPE = "tool_request"

#: A submission starts a paid session, so one requester cannot spend the budget in an afternoon by holding the enter
#: key. Deliberately generous for a demo; tighten before this is real.
MAX_REQUESTS_PER_DAY = 5

#: Namespace for the per-requester advisory lock, so the key cannot collide with another feature's lock.
_SUBMIT_LOCK_NAMESPACE = 8471003


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
    # Counting and inserting have to be one atomic step, or N concurrent submissions all read N-1 and all spend money.
    await db.execute(select(func.pg_advisory_xact_lock(_SUBMIT_LOCK_NAMESPACE, actor_id)))

    if get_tool(brief.slug_hint) is not None:
        raise ValidationError(f"A tool called '{brief.slug_hint}' already exists; pick another name")

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

    return await dispatch_request(db, actor, int(created["id"]), sees_all=True)


async def dispatch_request(db: AsyncSession, actor: dict[str, Any], request_id: int, sees_all: bool = False) -> dict[str, Any]:
    """Start (or retry) the Devin session for a stored request.

    A deployment with no API key leaves the request ``queued``: the page then shows the prompt to copy, which is the
    honest behaviour for a demo and for anyone who would rather start the session themselves.
    """
    # Row lock, not a bare read: two clicks on "Start the session" must not both reach the API and pay twice.
    await db.execute(select(ToolRequest.id).where(ToolRequest.id == request_id).with_for_update())
    stored = await get_request(db, request_id)

    requester_id = int(stored["requester_user_id"])
    if not sees_all and requester_id != int(actor["id"]):
        raise PermissionDeniedError("Only the requester or a request admin can start this session")
    if stored["status"] == STATUS_DISPATCHED:
        raise ValidationError(f"Request {request_id} already has a session")
    if stored["status"] not in RETRYABLE_STATUSES:
        raise ValidationError(
            f"Request {request_id} is already being started. If it stays here, check Devin for a session with the "
            f"tag tool:{stored['slug_hint']} before starting another one."
        )

    if not devin.is_configured():
        return stored

    # Claim the row and commit before the call goes out. The lock alone is not enough: a timeout after Devin accepted
    # the request would otherwise leave the row retryable, and the next click would pay for a second session.
    stored = await _record_dispatch(db, actor, stored, ToolRequestDispatch(status=STATUS_DISPATCHING))

    usernames = await usernames_for_ids(db, {requester_id})
    prompt = build_prompt(stored, usernames.get(requester_id, str(requester_id)))
    try:
        session = await devin.create_session(
            prompt,
            tags=[f"tool:{stored['slug_hint']}", "source:intake"],
            title=f"Add internal tool: {stored['title']}",
        )
    except devin.DevinNotConfigured:  # the key was removed between the check above and the call
        return await _record_dispatch(db, actor, stored, ToolRequestDispatch(status=STATUS_QUEUED))
    except devin.DevinDispatchError as exc:
        # An ambiguous failure stays claimed: a session may exist, and only a human can tell.
        message = f"{exc}. A session may have been created; check Devin before starting another." if exc.ambiguous else str(exc)
        return await _record_dispatch(
            db,
            actor,
            stored,
            ToolRequestDispatch(status=STATUS_DISPATCHING if exc.ambiguous else STATUS_FAILED, dispatch_error=message),
        )

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


_DISPATCH_ACTIONS = {
    STATUS_QUEUED: "intake.request.dispatch_skipped",
    STATUS_DISPATCHING: "intake.request.dispatching",
    STATUS_DISPATCHED: "intake.request.dispatched",
    STATUS_FAILED: "intake.request.dispatch_failed",
}


async def _record_dispatch(
    db: AsyncSession, actor: dict[str, Any], stored: dict[str, Any], outcome: ToolRequestDispatch
) -> dict[str, Any]:
    await crud_tool_requests.update(db=db, object=outcome, id=stored["id"], commit=False)
    await audit.record(
        db,
        actor,
        _DISPATCH_ACTIONS[outcome.status],
        ENTITY_TYPE,
        stored["id"],
        before={"status": stored["status"]},
        after={"status": outcome.status, "session_id": outcome.session_id, "error": outcome.dispatch_error},
    )
    await db.commit()
    return await get_request(db, int(stored["id"]))
