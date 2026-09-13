"""Permission dependencies used by every tool route.

``require_permission`` is the gate; ``current_permissions`` is what templates
use to decide what to render. Both resolve the logged-in session user, so a tool
route never touches roles directly.
"""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from crudauth.exceptions import ForbiddenException
from fastapi import Depends

from ...infrastructure.dependencies import AsyncSessionDep, CurrentUserDep, OptionalUserDep
from . import service


class LoginRequiredError(Exception):
    """Raised by HTML page dependencies when there is no session.

    Handled at the app level by redirecting to the login page — an API 401 body is useless to a browser that just wants
    the form.
    """

    def __init__(self, next_url: str | None = None) -> None:
        self.next_url = next_url
        super().__init__("Login required")


async def get_current_permissions(user: CurrentUserDep, db: AsyncSessionDep) -> set[str]:
    """The permission strings held by the logged-in user (superusers hold all)."""
    return await service.get_permissions_for_user(db, int(user["id"]), is_superuser=bool(user.get("is_superuser")))


CurrentPermissionsDep = Annotated[set[str], Depends(get_current_permissions)]


def require_permission(permission: str) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
    """Dependency factory gating a route on one flat permission string.

    Returns the current user dict so a route can depend on this alone::

        @router.post("/cases/{case_id}/approve")
        async def approve(user: Annotated[dict, Depends(require_permission("kyc.approve"))]): ...
    """

    async def dependency(user: CurrentUserDep, permissions: CurrentPermissionsDep) -> dict[str, Any]:
        if permission not in permissions:
            raise ForbiddenException(f"This action requires the '{permission}' permission")
        return user

    return dependency


@dataclass(frozen=True)
class ViewerContext:
    """Everything the shared layout needs about the current user."""

    user: dict[str, Any]
    roles: list[str]
    permissions: set[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions


async def get_viewer(db: AsyncSessionDep, user: OptionalUserDep) -> ViewerContext:
    """The signed-in viewer for an HTML page, or a redirect to the login page."""
    if user is None:
        raise LoginRequiredError()

    permissions = await service.get_permissions_for_user(db, int(user["id"]), is_superuser=bool(user.get("is_superuser")))
    roles = await service.list_user_role_names(db, user)
    return ViewerContext(user=user, roles=roles, permissions=permissions)


ViewerDep = Annotated[ViewerContext, Depends(get_viewer)]


def require_page_permission(permission: str) -> Callable[..., Coroutine[Any, Any, ViewerContext]]:
    """Like :func:`require_permission`, but for HTML pages (redirects anonymous users)."""

    async def dependency(viewer: ViewerDep) -> ViewerContext:
        if not viewer.can(permission):
            raise ForbiddenException(f"This page requires the '{permission}' permission")
        return viewer

    return dependency
