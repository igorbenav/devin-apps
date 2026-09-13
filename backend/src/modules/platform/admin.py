"""Permission gating for SQLAdmin views.

Lives in the platform module rather than under ``interfaces/`` so tool modules can gate their own admin views without
importing an interface layer.
"""

from typing import ClassVar

from starlette.requests import Request

from .constants import PERM_PLATFORM_ADMIN


def session_permissions(request: Request) -> set[str]:
    """Permissions stashed in the admin session at login."""
    return set(request.session.get("permissions", []))


def is_superuser(request: Request) -> bool:
    """Superuser, or the configured break-glass admin (which has no platform user)."""
    if "user_id" not in request.session:
        return bool(request.session.get("admin_authenticated", False))
    return bool(request.session.get("is_superuser", False))


class PermissionGatedView:
    """Hide and block a view unless the admin user holds ``required_permission``.

    Mix it in *before* ``ModelView`` so the overrides win: ``class FooAdmin(PermissionGatedView, ModelView, ...)``.
    Without it ``required_permission`` is an inert class attribute and the view is open to every admin user.
    """

    required_permission: ClassVar[str] = PERM_PLATFORM_ADMIN

    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    def is_accessible(self, request: Request) -> bool:
        return is_superuser(request) or self.required_permission in session_permissions(request)
