"""Pydantic schemas for the Refunds tool."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import STATE_REQUESTED

REASON_MIN_LENGTH = 10
REASON_MAX_LENGTH = 2000
AMOUNT_MAX_DIGITS = 10


class RefundRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_ref: str = Field(min_length=1, max_length=64)
    order_ref: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0, max_digits=AMOUNT_MAX_DIGITS, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    reason: str = Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH)
    requested_by: int | None = None
    state: str = STATE_REQUESTED

    @field_validator("currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class RefundRequestUpdate(BaseModel):
    """Only the fields a transition changes; the request itself is immutable once made."""

    model_config = ConfigDict(extra="forbid")

    state: str | None = None
    decided_by: int | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    processed_by: int | None = None
    processed_at: datetime | None = None


class RefundRequestRead(BaseModel):
    id: int
    customer_ref: str
    order_ref: str
    amount: Decimal
    currency: str
    reason: str
    state: str
    requested_by: int | None
    decided_by: int | None
    decision_reason: str | None
    decided_at: datetime | None
    processed_by: int | None
    processed_at: datetime | None
    created_at: datetime
