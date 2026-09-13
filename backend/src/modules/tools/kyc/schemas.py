"""Pydantic schemas for the KYC Review Queue tool."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import DOC_STATUS_RECEIVED, STATE_PENDING

REASON_MIN_LENGTH = 10


class KycCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_ref: str = Field(min_length=1, max_length=64)
    customer_name: str = Field(min_length=1, max_length=200)
    risk_score: int = Field(ge=0, le=100)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: str = STATE_PENDING
    assigned_to: int | None = None


class KycCaseUpdate(BaseModel):
    """Only the fields a transition changes; everything else is immutable here."""

    model_config = ConfigDict(extra="forbid")

    state: str | None = None
    assigned_to: int | None = None
    decided_by: int | None = None
    decision_reason: str | None = None


class KycCaseRead(BaseModel):
    id: int
    customer_ref: str
    customer_name: str
    risk_score: int
    submitted_at: datetime
    state: str
    assigned_to: int | None
    decided_by: int | None
    decision_reason: str | None
    created_at: datetime


class KycDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: int
    kind: str = Field(min_length=1, max_length=50)
    filename: str = Field(min_length=1, max_length=255)
    status: str = DOC_STATUS_RECEIVED


class KycDocumentRead(BaseModel):
    id: int
    case_id: int
    kind: str
    filename: str
    status: str
