"""Tables owned by the KYC Review Queue tool."""

from datetime import UTC, datetime
from typing import Final

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....platform_sdk import Base, TimestampMixin

STATE_PENDING: Final = "pending"
STATE_IN_REVIEW: Final = "in_review"
STATE_APPROVED: Final = "approved"
STATE_REJECTED: Final = "rejected"
STATE_ESCALATED: Final = "escalated"

ALL_STATES: Final[tuple[str, ...]] = (
    STATE_PENDING,
    STATE_IN_REVIEW,
    STATE_APPROVED,
    STATE_REJECTED,
    STATE_ESCALATED,
)
DECIDED_STATES: Final[tuple[str, ...]] = (STATE_APPROVED, STATE_REJECTED)

DOC_STATUS_RECEIVED: Final = "received"
DOC_STATUS_MISSING: Final = "missing"
DOC_STATUS_EXPIRED: Final = "expired"


class KycCase(Base, TimestampMixin):
    """One customer's KYC review, moving through the queue's states."""

    __tablename__ = "kyc_case"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    customer_ref: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    risk_score: Mapped[int] = mapped_column(Integer, index=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        index=True,
    )
    state: Mapped[str] = mapped_column(String(20), default=STATE_PENDING, index=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), default=None)
    decision_reason: Mapped[str | None] = mapped_column(Text, default=None)

    def __repr__(self) -> str:
        return f"KycCase(id={self.id}, state={self.state})"


class KycDocument(Base, TimestampMixin):
    """A document attached to a case.

    Filenames only — nothing is uploaded or stored.
    """

    __tablename__ = "kyc_document"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    case_id: Mapped[int] = mapped_column(ForeignKey("kyc_case.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=DOC_STATUS_RECEIVED)

    def __repr__(self) -> str:
        return f"KycDocument(id={self.id}, case_id={self.case_id}, kind={self.kind})"
