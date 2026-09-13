"""Admin views for the platform tables."""

from typing import Any

from sqladmin import ModelView
from starlette.requests import Request

from ....modules.platform.admin import AuditedAdminView, PermissionGatedView
from ....modules.platform.constants import PERM_AUDIT_READ, PERM_PLATFORM_ADMIN
from ....modules.platform.models import AuditEvent, Role, UserRole
from ..mixins import DataclassModelMixin

__all__ = ["AuditEventAdmin", "AuditedAdminView", "PermissionGatedView", "RoleAdmin", "UserRoleAdmin"]


class RoleAdmin(PermissionGatedView, AuditedAdminView, DataclassModelMixin, ModelView, model=Role):
    """Roles and the permission strings they grant."""

    required_permission = PERM_PLATFORM_ADMIN

    name = "Role"
    name_plural = "Roles"
    icon = "fa-solid fa-user-shield"
    category = "Users & Access"

    column_list = [Role.id, Role.name, Role.description, Role.permissions]
    column_searchable_list = [Role.name]
    column_sortable_list = [Role.id, Role.name]
    form_columns = [Role.name, Role.description, Role.permissions]


class UserRoleAdmin(PermissionGatedView, AuditedAdminView, DataclassModelMixin, ModelView, model=UserRole):
    """Role assignments."""

    required_permission = PERM_PLATFORM_ADMIN

    name = "Role assignment"
    name_plural = "Role assignments"
    icon = "fa-solid fa-id-badge"
    category = "Users & Access"

    column_list = [UserRole.id, UserRole.user_id, UserRole.role_id, UserRole.created_at]
    column_sortable_list = [UserRole.id, UserRole.user_id, UserRole.role_id]
    form_columns = [UserRole.user_id, UserRole.role_id]


class AuditEventAdmin(PermissionGatedView, ModelView, model=AuditEvent):
    """Read-only window on the append-only audit log."""

    required_permission = PERM_AUDIT_READ

    name = "Audit event"
    name_plural = "Audit log"
    icon = "fa-solid fa-clipboard-list"
    category = "Platform"

    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True
    can_export = False

    column_list = [
        AuditEvent.occurred_at,
        AuditEvent.actor_user_id,
        AuditEvent.action,
        AuditEvent.entity_type,
        AuditEvent.entity_id,
        AuditEvent.request_id,
        AuditEvent.ip,
    ]
    column_details_list = "__all__"
    column_searchable_list = [AuditEvent.action, AuditEvent.entity_type, AuditEvent.entity_id]
    column_sortable_list = [AuditEvent.occurred_at, AuditEvent.action, AuditEvent.entity_type]
    column_default_sort = [(AuditEvent.occurred_at, True)]

    async def insert_model(self, request: Request, data: dict[str, Any]) -> Any:
        raise NotImplementedError("The audit log is append-only and cannot be written from the admin")

    async def update_model(self, request: Request, pk: str, data: dict[str, Any]) -> Any:
        raise NotImplementedError("The audit log is append-only and cannot be edited")

    async def delete_model(self, request: Request, pk: str) -> None:
        raise NotImplementedError("The audit log is append-only and cannot be deleted")
