"""HTML routes for the Feature Flags tool.

Mounted by the platform at the ToolSpec's ``route_prefix``; every route is
behind the tool's permission, and no route writes directly — they call
``service``. Refusals come back as the re-rendered partial with an inline
message, the same convention the other tools use.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from crudauth.exceptions import ForbiddenException
from fastapi import APIRouter, Depends, Form, Request

from ....infrastructure.dependencies import AsyncSessionDep
from ...common.exceptions import DomainError
from ...platform.constants import PERM_FLAGS_WRITE
from ...platform.dependencies import ViewerContext, require_page_permission
from ...platform.templating import render
from . import service
from .tool import SPEC

router = APIRouter(include_in_schema=False)

ViewerDep = Annotated[ViewerContext, Depends(require_page_permission(SPEC.required_permission))]


def _list_context(flags: list[dict[str, Any]], viewer: ViewerContext, error: str | None = None) -> dict[str, Any]:
    return {
        "flags": flags,
        "can_write": viewer.can(PERM_FLAGS_WRITE),
        "error": error,
        "tool": SPEC,
    }


async def _render_table(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerContext,
    change: Callable[[], Awaitable[Any]],
) -> Any:
    """Apply a change and re-render the table, inline error or not."""
    error: str | None = None
    try:
        await change()
    except ForbiddenException as exc:
        error = exc.detail if isinstance(exc.detail, str) else str(exc)
    except DomainError as exc:
        error = str(exc)

    flags = await service.list_flags(db)
    return render(request, "flags/_table.html", viewer=viewer, context=_list_context(flags, viewer, error))


@router.get("")
async def list_page(request: Request, db: AsyncSessionDep, viewer: ViewerDep) -> Any:
    """Every flag, with a toggle per row for users who may write."""
    flags = await service.list_flags(db)
    return render(request, "flags/list.html", viewer=viewer, context=_list_context(flags, viewer))


@router.post("")
async def create_flag(
    request: Request,
    db: AsyncSessionDep,
    viewer: ViewerDep,
    key: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    rollout_percent: Annotated[int, Form()] = 100,
) -> Any:
    """HTMX action: create a flag, disabled, and re-render the table."""
    return await _render_table(
        request,
        db,
        viewer,
        lambda: service.create_flag(
            db,
            viewer.user,
            viewer.permissions,
            key=key.strip(),
            description=description.strip(),
            rollout_percent=rollout_percent,
        ),
    )


@router.post("/{flag_id}/toggle")
async def toggle_flag(request: Request, db: AsyncSessionDep, viewer: ViewerDep, flag_id: int) -> Any:
    """HTMX action: flip a flag and re-render the table."""
    return await _render_table(request, db, viewer, lambda: service.toggle_flag(db, viewer.user, viewer.permissions, flag_id))
