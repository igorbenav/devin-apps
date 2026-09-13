"""HTML routes for the KYC Review Queue tool.

Mounted by the platform at the ToolSpec's ``route_prefix``; every route is
behind the tool's permission, and no route writes directly — they call
``service``. Service refusals (a missing permission, the maker/checker rule, a
bad state) are rendered back into the partial the user is looking at instead of
turning into a JSON error, so the queue stays usable.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from crudauth.exceptions import ForbiddenException
from fastapi import APIRouter, Depends, Form, Request

from ....infrastructure.dependencies import AsyncSessionDep
from ...common.exceptions import DomainError
from ...platform import service as platform_service
from ...platform.dependencies import ViewerContext, require_page_permission
from ...platform.templating import render
from . import service
from .tool import SPEC

router = APIRouter(include_in_schema=False)

ViewerDep = Annotated[ViewerContext, Depends(require_page_permission(SPEC.required_permission))]

Transition = Callable[[], Awaitable[dict[str, Any]]]


async def _case_context(
    db: AsyncSessionDep,
    viewer: ViewerContext,
    case_id: int,
    error: str | None = None,
) -> dict[str, Any]:
    """Everything the detail panel renders: the case, its documents and its trail."""
    case = await service.get_case(db, case_id)
    events = await platform_service.list_audit_events(db, entity_type=service.ENTITY_TYPE, entity_id=str(case_id))
    return {
        "case": case,
        "documents": await service.list_documents(db, case_id),
        "usernames": await service.usernames_for(db, [case]),
        "actions": service.allowed_actions(case, viewer.user, viewer.permissions),
        "events": events,
        "error": error,
        "tool": SPEC,
    }


async def _row_context(
    db: AsyncSessionDep,
    viewer: ViewerContext,
    case_id: int,
    error: str | None = None,
) -> dict[str, Any]:
    case = await service.get_case(db, case_id)
    return {
        "case": case,
        "usernames": await service.usernames_for(db, [case]),
        "actions": service.allowed_actions(case, viewer.user, viewer.permissions),
        "error": error,
    }


async def _respond(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerContext,
    case_id: int,
    view: str,
    transition: Transition,
) -> Any:
    """Run a transition and re-render the caller's partial, error or not.

    HTMX only swaps 2xx responses, so a refusal comes back as the same partial with an inline message rather than a
    status code the page cannot show.
    """
    error: str | None = None
    try:
        await transition()
    except ForbiddenException as exc:
        error = exc.detail if isinstance(exc.detail, str) else str(exc)
    except DomainError as exc:
        error = str(exc)

    if view == "row":
        return render(request, "kyc/_row.html", viewer=viewer, context=await _row_context(db, viewer, case_id, error))
    return render(request, "kyc/_detail.html", viewer=viewer, context=await _case_context(db, viewer, case_id, error))


@router.get("")
async def list_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep, tab: str = service.TAB_PENDING) -> Any:
    """The queue, one tab at a time."""
    if tab not in {name for name, _ in service.TABS}:
        tab = service.TAB_PENDING

    cases = await service.list_cases(db, tab, viewer.user)
    return render(
        request,
        "kyc/list.html",
        viewer=viewer,
        context={
            "cases": cases,
            "usernames": await service.usernames_for(db, cases),
            "actions_by_case": {case["id"]: service.allowed_actions(case, viewer.user, viewer.permissions) for case in cases},
            "tab": tab,
            "tabs": service.TABS,
            "tool": SPEC,
        },
    )


@router.get("/{case_id}")
async def detail_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep, case_id: int) -> Any:
    """One case: documents, state, the actions this user may take, and its audit trail."""
    return render(request, "kyc/detail.html", viewer=viewer, context=await _case_context(db, viewer, case_id))


@router.post("/{case_id}/claim")
async def claim(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    case_id: int,
    view: Annotated[str, Form()] = "row",
) -> Any:
    """HTMX action: take an unassigned pending case into review."""
    return await _respond(
        request, db, viewer, case_id, view, lambda: service.claim_case(db, viewer.user, viewer.permissions, case_id)
    )


@router.post("/{case_id}/release")
async def release(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    case_id: int,
    view: Annotated[str, Form()] = "row",
) -> Any:
    """HTMX action: put a case back in the pending queue."""
    return await _respond(
        request, db, viewer, case_id, view, lambda: service.release_case(db, viewer.user, viewer.permissions, case_id)
    )


@router.post("/{case_id}/approve")
async def approve(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    case_id: int,
    reason: Annotated[str, Form()] = "",
    view: Annotated[str, Form()] = "detail",
) -> Any:
    """HTMX action: approve, if the maker/checker rule allows it."""
    return await _respond(
        request,
        db,
        viewer,
        case_id,
        view,
        lambda: service.approve_case(db, viewer.user, viewer.permissions, case_id, reason),
    )


@router.post("/{case_id}/reject")
async def reject(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    case_id: int,
    reason: Annotated[str, Form()] = "",
    view: Annotated[str, Form()] = "detail",
) -> Any:
    """HTMX action: reject, if the maker/checker rule allows it."""
    return await _respond(
        request,
        db,
        viewer,
        case_id,
        view,
        lambda: service.reject_case(db, viewer.user, viewer.permissions, case_id, reason),
    )


@router.post("/{case_id}/escalate")
async def escalate(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    case_id: int,
    reason: Annotated[str, Form()] = "",
    view: Annotated[str, Form()] = "detail",
) -> Any:
    """HTMX action: escalate a case under review."""
    return await _respond(
        request,
        db,
        viewer,
        case_id,
        view,
        lambda: service.escalate_case(db, viewer.user, viewer.permissions, case_id, reason),
    )


@router.post("/{case_id}/resume")
async def resume(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    case_id: int,
    view: Annotated[str, Form()] = "detail",
) -> Any:
    """HTMX action: bring an escalated case back into review."""
    return await _respond(
        request, db, viewer, case_id, view, lambda: service.resume_case(db, viewer.user, viewer.permissions, case_id)
    )
