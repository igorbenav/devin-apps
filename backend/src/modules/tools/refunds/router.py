"""HTML routes for the Refunds tool.

Mounted by the platform at the manifest's ``route_prefix``; every route is behind the tool's
view permission, and no route writes directly — they call ``service``, which re-checks the
permission and the domain rule behind every button.

Refusals (a missing permission, self-approval, a reason the high-value rule needs, a refund that
has already been paid out) are rendered back into the partial the user is looking at, so the
dashboard stays usable instead of turning into a JSON error page.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from crudauth.exceptions import ForbiddenException
from fastapi import APIRouter, Depends, Form, Request
from pydantic import ValidationError as PydanticValidationError

from ....platform_sdk import (
    AsyncSessionDep,
    DomainError,
    ViewerContext,
    get_tool,
    list_audit_events,
    render,
    require_page_permission,
)
from . import service
from .permissions import PERM_REFUNDS_REQUEST, REQUIRED_PERMISSION, SLUG
from .schemas import RefundRequestCreate

router = APIRouter(include_in_schema=False)

ViewerDep = Annotated[ViewerContext, Depends(require_page_permission(REQUIRED_PERMISSION))]

Transition = Callable[[], Awaitable[dict[str, Any]]]

CREATE_FIELDS = ("customer_ref", "order_ref", "amount", "currency", "reason")


async def _board_context(
    db: AsyncSessionDep,
    viewer: ViewerContext,
    state: str,
    error: str | None = None,
    answers: dict[str, str] | None = None,
    flash: str | None = None,
) -> dict[str, Any]:
    """The dashboard: the three counts, the filtered table, and the agent's create form."""
    refunds = await service.list_refunds(db, state)
    return {
        "counts": await service.dashboard_counts(db),
        "refunds": refunds,
        "usernames": await service.usernames_for(db, refunds),
        "actions_by_refund": {
            refund["id"]: service.allowed_actions(refund, viewer.user, viewer.permissions) for refund in refunds
        },
        "state": state,
        "state_filters": service.STATE_FILTERS,
        "can_request": PERM_REFUNDS_REQUEST in viewer.permissions,
        "answers": answers or {},
        "error": error,
        "flash": flash,
    }


async def _detail_context(
    db: AsyncSessionDep,
    viewer: ViewerContext,
    refund_id: int,
    error: str | None = None,
) -> dict[str, Any]:
    """One refund, the actions this viewer may take on it, and its audit trail."""
    refund = await service.get_refund(db, refund_id)
    return {
        "refund": refund,
        "usernames": await service.usernames_for(db, [refund]),
        "actions": service.allowed_actions(refund, viewer.user, viewer.permissions),
        "events": await list_audit_events(db, entity_type=service.ENTITY_TYPE, entity_id=str(refund_id)),
        "error": error,
    }


async def _respond(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerContext,
    refund_id: int,
    view: str,
    state: str,
    transition: Transition,
) -> Any:
    """Run a transition and re-render the caller's partial, error or not.

    HTMX only swaps 2xx responses, so a refusal comes back as the same partial with the reason in it rather than a
    status code the page cannot show.

    A transition moves a refund between states, which moves the counts and can drop it out of the filter the table is
    showing, so the dashboard is re-rendered whole rather than row by row.
    """
    error: str | None = None
    try:
        await transition()
    except ForbiddenException as exc:
        error = exc.detail if isinstance(exc.detail, str) else str(exc)
    except DomainError as exc:
        error = str(exc)

    if view == "board":
        return render(
            request, "refunds/_board.html", viewer=viewer, context=await _board_context(db, viewer, state, error=error)
        )
    return render(request, "refunds/_detail.html", viewer=viewer, context=await _detail_context(db, viewer, refund_id, error))


@router.get("")
async def list_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep, state: str = service.FILTER_ALL) -> Any:
    """The dashboard: what is outstanding, what has been paid out, and everything else."""
    if state not in {name for name, _ in service.STATE_FILTERS}:
        state = service.FILTER_ALL

    return render(
        request,
        "refunds/list.html",
        viewer=viewer,
        context={**await _board_context(db, viewer, state), "tool": get_tool(SLUG)},
    )


@router.post("")
async def create_refund(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    state: Annotated[str, Form()] = service.FILTER_ALL,
) -> Any:
    """HTMX action: raise a refund request, keeping the answers if it is refused."""
    form = await request.form()
    answers = {field: str(form.get(field) or "") for field in CREATE_FIELDS}

    error: str | None = None
    flash: str | None = None
    try:
        payload = RefundRequestCreate.model_validate(answers)
        created = await service.create_refund(db, viewer.user, viewer.permissions, payload)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        error = f"{first['loc'][0]}: {first['msg'].removeprefix('Value error, ')}"
    except ForbiddenException as exc:
        error = exc.detail if isinstance(exc.detail, str) else str(exc)
    except DomainError as exc:
        error = str(exc)
    else:
        flash = f"Refund #{created['id']} requested."
        answers = {}

    context = await _board_context(db, viewer, state, error=error, answers=answers, flash=flash)
    return render(request, "refunds/_board.html", viewer=viewer, context=context)


@router.get("/{refund_id}")
async def detail_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep, refund_id: int) -> Any:
    """One refund: its facts, the actions this user may take, and who did what, when and why."""
    return render(
        request,
        "refunds/detail.html",
        viewer=viewer,
        context={**await _detail_context(db, viewer, refund_id), "tool": get_tool(SLUG)},
    )


@router.post("/{refund_id}/approve")
async def approve(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    refund_id: int,
    reason: Annotated[str, Form()] = "",
    view: Annotated[str, Form()] = "detail",
    state: Annotated[str, Form()] = service.FILTER_ALL,
) -> Any:
    """HTMX action: approve a requested refund, with the reason that approval needs."""
    return await _respond(
        request,
        db,
        viewer,
        refund_id,
        view,
        state,
        lambda: service.approve_refund(db, viewer.user, viewer.permissions, refund_id, reason),
    )


@router.post("/{refund_id}/reject")
async def reject(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    refund_id: int,
    reason: Annotated[str, Form()] = "",
    view: Annotated[str, Form()] = "detail",
    state: Annotated[str, Form()] = service.FILTER_ALL,
) -> Any:
    """HTMX action: reject a requested refund, which is the end of it."""
    return await _respond(
        request,
        db,
        viewer,
        refund_id,
        view,
        state,
        lambda: service.reject_refund(db, viewer.user, viewer.permissions, refund_id, reason),
    )


@router.post("/{refund_id}/process")
async def process(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    refund_id: int,
    view: Annotated[str, Form()] = "board",
    state: Annotated[str, Form()] = service.FILTER_ALL,
) -> Any:
    """HTMX action: mark an approved refund as paid out."""
    return await _respond(
        request,
        db,
        viewer,
        refund_id,
        view,
        state,
        lambda: service.process_refund(db, viewer.user, viewer.permissions, refund_id),
    )
