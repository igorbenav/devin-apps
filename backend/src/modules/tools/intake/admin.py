"""SQLAdmin view for the Tool Requests tool."""

from sqladmin import ModelView

from ....platform_sdk import PERM_PLATFORM_ADMIN, AuditedAdminView, PermissionGatedView
from .models import ToolRequest


class ToolRequestAdmin(PermissionGatedView, AuditedAdminView, ModelView, model=ToolRequest):
    """Back-office view of submitted briefs.

    Read-only: a request is evidence of what was asked for, and editing it after the session ran would make the audit
    trail lie.
    """

    required_permission = PERM_PLATFORM_ADMIN

    name = "Tool Request"
    name_plural = "Tool Requests"
    icon = "fa-solid fa-clipboard-list"
    category = "Internal Tools"

    column_list = [
        ToolRequest.id,
        ToolRequest.title,
        ToolRequest.slug_hint,
        ToolRequest.requester_user_id,
        ToolRequest.status,
        ToolRequest.created_at,
    ]
    column_searchable_list = [ToolRequest.title, ToolRequest.slug_hint]
    column_sortable_list = [ToolRequest.id, ToolRequest.status, ToolRequest.created_at]

    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True
