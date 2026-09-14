"""Tables owned by the Refunds tool."""

from datetime import datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....platform_sdk import Base, TimestampMixin

STATE_REQUESTED: Final = "requested"
STATE_APPROVED: Final = "approved"
STATE_REJECTED: Final = "rejected"
STATE_PROCESSED: Final = "processed"

ALL_STATES: Final[tuple[str, ...]] = (STATE_REQUESTED, STATE_APPROVED, STATE_REJECTED, STATE_PROCESSED)
TERMINAL_STATES: Final[tuple[str, ...]] = (STATE_REJECTED, STATE_PROCESSED)

AMOUNT_PRECISION: Final = 12
AMOUNT_SCALE: Final = 2

# Above this amount, in whatever currency the refund is in, a decision without a reason is refused.
HIGH_VALUE_THRESHOLD: Final = Decimal("1000")


class RefundRequest(Base, TimestampMixin):
    """One refund a support agent asked for, moving through the approval states.

    ``requested`` is where every refund starts; a team lead moves it to ``approved`` or
    ``rejected``, and an agent moves an approved refund to ``processed`` once the money has
    gone out. ``rejected`` and ``processed`` are terminal.
    """

    __tablename__ = "refunds_request"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    customer_ref: Mapped[str] = mapped_column(String(64), index=True)
    order_ref: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(AMOUNT_PRECISION, AMOUNT_SCALE))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), index=True)
    state: Mapped[str] = mapped_column(String(20), default=STATE_REQUESTED, index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), default=None)
    decision_reason: Mapped[str | None] = mapped_column(Text, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    processed_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), default=None)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)

    def __repr__(self) -> str:
        return f"RefundRequest(id={self.id}, state={self.state})"
