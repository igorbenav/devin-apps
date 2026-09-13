"""Tables owned by the Tool Requests tool."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....platform_sdk import Base, TimestampMixin

STATUS_QUEUED = "queued"
#: Claimed: the API call is in flight, or it ended in a way that may or may not have created a session. Either way
#: nobody may dispatch this request again without checking Devin first.
STATUS_DISPATCHING = "dispatching"
STATUS_DISPATCHED = "dispatched"
STATUS_FAILED = "failed"

#: The statuses a dispatch may be started from. ``dispatching`` is deliberately absent.
RETRYABLE_STATUSES = frozenset({STATUS_QUEUED, STATUS_FAILED})

STATUS_LABELS = {
    STATUS_QUEUED: "Queued",
    STATUS_DISPATCHING: "Starting…",
    STATUS_DISPATCHED: "Session started",
    STATUS_FAILED: "Dispatch failed",
}


class ToolRequest(Base, TimestampMixin):
    """One filled-in tool brief, and the Devin session started from it.

    The columns after ``slug_hint`` are the brief questions from ``UX.md``; they are stored as written so the prompt can
    be rebuilt and re-dispatched without the requester filling the form in again.
    """

    __tablename__ = "tool_request"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True, init=False)
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    slug_hint: Mapped[str] = mapped_column(String(50))

    users: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    today: Mapped[str] = mapped_column(Text)
    states: Mapped[str] = mapped_column(Text)
    must_never_happen: Mapped[str] = mapped_column(Text)
    provable: Mapped[str] = mapped_column(Text)
    data_sources: Mapped[str] = mapped_column(Text)
    volume: Mapped[str] = mapped_column(Text)
    success: Mapped[str] = mapped_column(Text)
    out_of_scope: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default=STATUS_QUEUED, index=True)
    session_id: Mapped[str | None] = mapped_column(String(100), default=None)
    session_url: Mapped[str | None] = mapped_column(String(500), default=None)
    dispatch_error: Mapped[str | None] = mapped_column(Text, default=None)

    def __repr__(self) -> str:
        return f"ToolRequest(id={self.id}, slug_hint={self.slug_hint}, status={self.status})"
