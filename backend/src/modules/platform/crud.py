"""FastCRUD instances for the platform tables.

The audit log is append-only, so its CRUD object is an :class:`AppendOnlyCRUD`
that removes every mutating path FastCRUD would otherwise provide.
"""

from typing import Any, NoReturn

from fastcrud import FastCRUD

from .models import AuditEvent, Role, UserRole

crud_roles: FastCRUD = FastCRUD(Role)
crud_user_roles: FastCRUD = FastCRUD(UserRole)


class AppendOnlyCRUD(FastCRUD):
    """FastCRUD restricted to create and read.

    Anything that would mutate or remove an existing row raises
    ``NotImplementedError`` instead of silently working, so an append-only table
    cannot be rewritten by accident (including through the admin or a future
    tool module).
    """

    def _forbid(self, operation: str) -> NoReturn:
        raise NotImplementedError(f"{self.model.__name__} is append-only: {operation} is not available")

    async def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._forbid("update")

    async def upsert(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._forbid("upsert")

    async def upsert_multi(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._forbid("upsert_multi")

    async def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._forbid("delete")

    async def db_delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._forbid("db_delete")


crud_audit_events: AppendOnlyCRUD = AppendOnlyCRUD(AuditEvent)
