"""Platform tables: roles, role assignments, and the append-only audit log."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ...infrastructure.database.models import TimestampMixin
from ...infrastructure.database.session import Base
from .constants import (
    ACTION_MAX_LENGTH,
    ENTITY_ID_MAX_LENGTH,
    ENTITY_TYPE_MAX_LENGTH,
    IP_MAX_LENGTH,
    REQUEST_ID_MAX_LENGTH,
    ROLE_NAME_MAX_LENGTH,
)


class Role(Base, TimestampMixin):
    """A named bundle of flat permission strings."""

    __tablename__ = "platform_role"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    name: Mapped[str] = mapped_column(String(ROLE_NAME_MAX_LENGTH), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    permissions: Mapped[list[str]] = mapped_column(JSON, default_factory=list)

    def __repr__(self) -> str:
        return self.name


class UserRole(Base, TimestampMixin):
    """Assignment of a :class:`Role` to a user."""

    __tablename__ = "platform_user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_platform_user_role_user_id_role_id"),)

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("platform_role.id", ondelete="CASCADE"), index=True)

    def __repr__(self) -> str:
        return f"user={self.user_id} role={self.role_id}"


class AuditEvent(Base):
    """Append-only record of a state change made through a tool service.

    Rows are never updated or deleted: the CRUD layer for this table
    (:data:`~src.modules.platform.crud.crud_audit_events`) exposes creation and
    reads only, and the SQLAdmin view is read-only.
    """

    __tablename__ = "platform_audit_event"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    action: Mapped[str] = mapped_column(String(ACTION_MAX_LENGTH), index=True)
    entity_type: Mapped[str] = mapped_column(String(ENTITY_TYPE_MAX_LENGTH), index=True)
    entity_id: Mapped[str] = mapped_column(String(ENTITY_ID_MAX_LENGTH), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), index=True, default=None)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH), default=None)
    ip: Mapped[str | None] = mapped_column(String(IP_MAX_LENGTH), default=None)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        index=True,
    )

    def __repr__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id}"
