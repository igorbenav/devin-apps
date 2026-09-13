"""The only import surface a tool module is allowed to use.

Everything a tool needs from the rest of the app is re-exported here: the tool
manifest, permission gates, the audit writer, the shared renderer, the audited
SQLAdmin bases, and the database/session plumbing. Tools import
``src.platform_sdk`` and their own package — nothing else. ``.importlinter``
enforces that.

The point is refactorability at fifty tools: this module is the compatibility
surface, so the platform internals behind it can move without touching every
tool. Anything not exported here is internal; if a tool needs something new,
add it here deliberately rather than reaching into ``modules.platform``.
"""

from ..infrastructure.database.models import TimestampMixin
from ..infrastructure.database.session import Base
from ..infrastructure.dependencies import AsyncSessionDep
from ..modules.api_keys.dependencies import enforce_api_key_rate_limit, require_api_key
from ..modules.api_keys.enums import KeyPermissionAction, KeyPermissionResource
from ..modules.api_keys.schemas import APIKeyValidationResponse
from ..modules.common.exceptions import (
    DomainError,
    PermissionDeniedError,
    ResourceExistsError,
    ResourceNotFoundError,
    ValidationError,
)
from ..modules.platform import audit
from ..modules.platform.admin import AuditedAdminView, PermissionGatedView, jsonable, snapshot
from ..modules.platform.audit import Actor, actor_id
from ..modules.platform.constants import PERM_PLATFORM_ADMIN
from ..modules.platform.dependencies import (
    CurrentPermissionsDep,
    ViewerContext,
    ViewerDep,
    require_page_permission,
    require_permission,
)
from ..modules.platform.registry import Permission, ToolSpec, get_tool, register
from ..modules.platform.service import issue_api_key, list_audit_events, user_id_by_username, usernames_for_ids
from ..modules.platform.templating import render

__all__ = [
    "APIKeyValidationResponse",
    "Actor",
    "AsyncSessionDep",
    "AuditedAdminView",
    "Base",
    "CurrentPermissionsDep",
    "DomainError",
    "KeyPermissionAction",
    "KeyPermissionResource",
    "PERM_PLATFORM_ADMIN",
    "Permission",
    "PermissionDeniedError",
    "PermissionGatedView",
    "ResourceExistsError",
    "ResourceNotFoundError",
    "TimestampMixin",
    "ToolSpec",
    "ValidationError",
    "ViewerContext",
    "ViewerDep",
    "actor_id",
    "audit",
    "enforce_api_key_rate_limit",
    "get_tool",
    "issue_api_key",
    "jsonable",
    "list_audit_events",
    "register",
    "render",
    "require_api_key",
    "require_page_permission",
    "require_permission",
    "snapshot",
    "user_id_by_username",
    "usernames_for_ids",
]
