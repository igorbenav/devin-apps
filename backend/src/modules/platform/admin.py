"""Permission gating and audit trailing for SQLAdmin views.

Lives in the platform module rather than under ``interfaces/`` so tool modules can gate their own admin views without
importing an interface layer.
"""

import datetime
import decimal
import uuid
from typing import Any, ClassVar

from sqlalchemy import inspect as sa_inspect
from starlette.requests import Request

from ...infrastructure.database.session import local_session
from . import audit
from .constants import PERM_PLATFORM_ADMIN

AUDIT_BEFORE_STATE_KEY = "admin_audit_before"


def _request_state(request: Request) -> dict[str, Any]:
    """The per-request scope dict behind ``request.state``, typed."""
    state: dict[str, Any] = request.scope.setdefault("state", {})
    return state


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


def jsonable(value: Any) -> Any:
    """Narrow a column value to something the audit JSON column can hold."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime.datetime | datetime.date | datetime.time | uuid.UUID):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return str(value)


SECRET_COLUMNS = frozenset({"hashed_password", "password", "key_hash", "salt", "secret", "token"})


def snapshot(model: Any, exclude: frozenset[str] = SECRET_COLUMNS) -> dict[str, Any]:
    """Column values of a mapped instance, as audit-storable JSON, minus credential columns."""
    state = sa_inspect(model)
    return {attr.key: jsonable(state.dict.get(attr.key)) for attr in state.mapper.column_attrs if attr.key not in exclude}


class AuditedAdminView:
    """Record an audit event for every create, edit and delete made through SQLAdmin.

    Admin writes go straight to the table through SQLAdmin's own session, bypassing the service functions that normally
    do the recording. The event is written after SQLAdmin commits, in its own transaction, so unlike a service-layer
    write it is not atomic with the change it describes — a change can land while its audit row fails. Still strictly
    better than an unrecorded admin edit.

    Mix it in before ``ModelView``: ``class FooAdmin(PermissionGatedView, AuditedAdminView, ModelView, ...)``.
    """

    # Set by ``ModelView`` through its ``model=`` class argument; declared so this mixin type-checks on its own.
    model: ClassVar[type[Any]]

    audit_entity_type: ClassVar[str] = ""
    audit_excluded_columns: ClassVar[frozenset[str]] = SECRET_COLUMNS

    def _entity_type(self) -> str:
        return self.audit_entity_type or str(sa_inspect(self.model).local_table.name)

    async def _record(self, request: Request, verb: str, model: Any, before: dict[str, Any] | None) -> None:
        entity_type = self._entity_type()
        after = None if verb == "deleted" else snapshot(model, self.audit_excluded_columns)
        identity = sa_inspect(model).identity
        fallback = after or before or {}
        entity_id = identity[0] if identity else fallback.get("id")

        async with local_session() as db:
            await audit.record(
                db,
                request.session.get("user_id"),
                f"admin.{entity_type}.{verb}",
                entity_type,
                entity_id,
                before=before,
                after=after,
            )
            await db.commit()

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        before = None if is_created else snapshot(model, self.audit_excluded_columns)
        _request_state(request)[AUDIT_BEFORE_STATE_KEY] = before

    async def after_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        before = _request_state(request).get(AUDIT_BEFORE_STATE_KEY)
        await self._record(request, "created" if is_created else "updated", model, before)

    async def on_model_delete(self, model: Any, request: Request) -> None:
        _request_state(request)[AUDIT_BEFORE_STATE_KEY] = snapshot(model, self.audit_excluded_columns)

    async def after_model_delete(self, model: Any, request: Request) -> None:
        before = _request_state(request).get(AUDIT_BEFORE_STATE_KEY)
        await self._record(request, "deleted", model, before)
