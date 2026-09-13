"""Pydantic schemas for the Feature Flags tool."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

KEY_PATTERN = r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$"


class FlagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100, pattern=KEY_PATTERN)
    description: str = ""
    enabled: bool = False
    rollout_percent: int = Field(default=100, ge=0, le=100)
    updated_by: int | None = None


class FlagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    enabled: bool | None = None
    rollout_percent: int | None = Field(default=None, ge=0, le=100)
    updated_by: int | None = None


class FlagRead(BaseModel):
    id: int
    key: str
    description: str
    enabled: bool
    rollout_percent: int
    updated_by: int | None
    updated_at: datetime | None


class FlagEvaluation(BaseModel):
    """What a service gets back from ``/api/v1/flags/evaluate``."""

    key: str
    enabled: bool
    reason: str
