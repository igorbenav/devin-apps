"""Tables owned by the Feature Flags tool."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....infrastructure.database.models import TimestampMixin
from ....infrastructure.database.session import Base


class Flag(Base, TimestampMixin):
    """One feature flag, evaluated by services through the API."""

    __tablename__ = "feature_flag"
    __table_args__ = (CheckConstraint("rollout_percent BETWEEN 0 AND 100", name="ck_feature_flag_rollout_percent"),)

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, default=100)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), default=None)

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=True,
        init=False,
    )

    def __repr__(self) -> str:
        return f"Flag(key={self.key}, enabled={self.enabled}, rollout_percent={self.rollout_percent})"
