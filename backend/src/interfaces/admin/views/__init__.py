"""SQLAdmin model views for the admin interface.

Platform views are listed here; tool views come from the tool registry, so adding a tool never edits this file.
"""

from sqladmin import Admin

from ....modules.platform.registry import register_tool_admin_views
from .platform import AuditEventAdmin, RoleAdmin, UserRoleAdmin
from .tiers import TierAdmin
from .users import UserAdmin

__all__ = [
    "UserAdmin",
    "TierAdmin",
    "RoleAdmin",
    "UserRoleAdmin",
    "AuditEventAdmin",
    "register_admin_views",
]


def register_admin_views(admin: Admin) -> None:
    """Register all model views with the admin interface."""
    admin.add_view(UserAdmin)
    admin.add_view(TierAdmin)
    admin.add_view(RoleAdmin)
    admin.add_view(UserRoleAdmin)
    admin.add_view(AuditEventAdmin)
    register_tool_admin_views(admin)
