"""Pydantic schemas for the platform module."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .constants import ROLE_NAME_MAX_LENGTH


class RoleBase(BaseModel):
    name: str = Field(min_length=2, max_length=ROLE_NAME_MAX_LENGTH, examples=["analyst"])
    description: str | None = Field(default=None, examples=["Reviews KYC cases"])
    permissions: list[str] = Field(default_factory=list, examples=[["kyc.review", "flags.read"]])


class RoleCreate(RoleBase):
    model_config = ConfigDict(extra="forbid")


class RoleRead(RoleBase):
    id: int


class UserRoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    role_id: int


class UserRoleRead(UserRoleCreate):
    id: int


class AuditEventCreate(BaseModel):
    """Internal write schema — only :func:`src.modules.platform.audit.record` builds it."""

    model_config = ConfigDict(extra="forbid")

    action: str
    entity_type: str
    entity_id: str
    actor_user_id: int | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    request_id: str | None = None
    ip: str | None = None


class AuditEventRead(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: int | None
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    ip: str | None
