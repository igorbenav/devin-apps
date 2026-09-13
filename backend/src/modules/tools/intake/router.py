"""HTML routes for the Tool Requests tool.

Mounted by the platform at the manifest's ``route_prefix``; every route is behind the tool's permission, and no route
writes directly — they call ``service``. Validation failures come back as the same page with the answers still in the
form, because retyping ten questions to fix one of them is how an intake stops being used.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError as PydanticValidationError

from ....platform_sdk import (
    AsyncSessionDep,
    DomainError,
    PermissionDeniedError,
    ViewerContext,
    get_tool,
    render,
    require_page_permission,
    usernames_for_ids,
)
from . import devin, service
from .models import STATUS_LABELS
from .permissions import PERM_REQUEST_ADMIN, REQUIRED_PERMISSION, SLUG
from .prompt import build_prompt
from .schemas import BRIEF_QUESTIONS, ToolRequestBrief

router = APIRouter(include_in_schema=False)

ViewerDep = Annotated[ViewerContext, Depends(require_page_permission(REQUIRED_PERMISSION))]


async def _list_context(db: AsyncSessionDep, viewer: ViewerContext, **extra: Any) -> dict[str, Any]:
    sees_all = PERM_REQUEST_ADMIN in viewer.permissions
    requests = await service.list_requests(db, requester_user_id=None if sees_all else int(viewer.user["id"]))
    return {
        "requests": requests,
        "usernames": await usernames_for_ids(db, {int(item["requester_user_id"]) for item in requests}),
        "questions": BRIEF_QUESTIONS,
        "status_labels": STATUS_LABELS,
        "sees_all": sees_all,
        "devin_configured": devin.is_configured(),
        "tool": get_tool(SLUG),
        "answers": {},
        "error": None,
        **extra,
    }


@router.get("")
async def list_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep) -> Any:
    """The brief form, plus the requests this viewer may see."""
    return render(request, "intake/list.html", viewer=viewer, context=await _list_context(db, viewer))


@router.post("")
async def submit(request: Request, db: AsyncSessionDep, viewer: ViewerDep) -> Any:
    """Record a brief and start the session for it."""
    form = await request.form()
    fields = ("title", "slug_hint", *(name for name, _ in BRIEF_QUESTIONS))
    answers = {field: str(form.get(field) or "") for field in fields}

    error: str | None = None
    try:
        created = await service.submit_request(db, viewer.user, ToolRequestBrief(**answers))
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        error = f"{first['loc'][0]}: {first['msg'].removeprefix('Value error, ')}"
    except DomainError as exc:
        error = str(exc)
    else:
        return render(
            request,
            "intake/_requests.html",
            viewer=viewer,
            context=await _list_context(db, viewer, flash=f"Request #{created['id']} recorded."),
        )

    context = await _list_context(db, viewer, error=error, answers=answers)
    return render(request, "intake/_requests.html", viewer=viewer, context=context)


@router.get("/{request_id}")
async def detail_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep, request_id: int) -> Any:
    """One request: its answers, its status, and the prompt that was sent."""
    stored = await service.get_request(db, request_id)
    if not _may_act_on(stored, viewer):
        raise PermissionDeniedError("This request belongs to someone else")

    usernames = await usernames_for_ids(db, {int(stored["requester_user_id"])})
    requester = usernames.get(int(stored["requester_user_id"]), str(stored["requester_user_id"]))
    return render(
        request,
        "intake/detail.html",
        viewer=viewer,
        context={
            "item": stored,
            "requester": requester,
            "questions": BRIEF_QUESTIONS,
            "status_labels": STATUS_LABELS,
            "prompt": build_prompt(stored, requester),
            "can_retry": True,
            "devin_configured": devin.is_configured(),
            "tool": get_tool(SLUG),
            "error": None,
        },
    )


@router.post("/{request_id}/dispatch")
async def retry_dispatch(request: Request, db: AsyncSessionDep, viewer: ViewerDep, request_id: int) -> Any:
    """HTMX action: retry a failed or never-dispatched session."""
    stored = await service.get_request(db, request_id)
    error: str | None = None
    if not _may_act_on(stored, viewer):
        error = "Only the requester or a request admin can start this session"
    else:
        try:
            stored = await service.dispatch_request(db, viewer.user, request_id)
        except DomainError as exc:
            error = str(exc)

    return render(
        request,
        "intake/_status.html",
        viewer=viewer,
        context={
            "item": stored,
            "error": error,
            "status_labels": STATUS_LABELS,
            "devin_configured": devin.is_configured(),
            "can_retry": True,
        },
    )


def _may_act_on(stored: dict[str, Any], viewer: ViewerContext) -> bool:
    """The requester sees and retries their own request; a request admin sees everyone's."""
    return PERM_REQUEST_ADMIN in viewer.permissions or int(stored["requester_user_id"]) == int(viewer.user["id"])
