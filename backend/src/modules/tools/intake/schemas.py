"""Pydantic schemas for the Tool Requests tool."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import STATUS_QUEUED

#: The same shape `bp new tool` accepts, because the slug becomes a Python module name: lowercase, digits,
#: underscores. A hyphen here would validate here and then fail in the generator, inside a paid session.
SLUG_PATTERN = r"^[a-z][a-z0-9_]{1,48}[a-z0-9]$"

RESERVED_SLUGS = frozenset({"platform", "admin", "audit", "static", "api"})

#: Brief question text, keyed by the column that stores the answer. Drives the form, the detail page and the prompt, so
#: the three can never drift apart.
BRIEF_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("users", "Who uses this, and what is their job title?"),
    ("decision", "What decision or action does it let them take that they can't take now?"),
    ("today", "What do they do today instead (spreadsheet, email, Power Apps, nothing)?"),
    ("states", "What are the states a record moves through, and who can move it between them?"),
    ("must_never_happen", "What must never happen? (e.g. the same person approves their own case)"),
    ("provable", "What has to be provable afterwards, and to whom?"),
    ("data_sources", "Where does the data come from, and where does it need to go?"),
    ("volume", "How many records a day, and how many people?"),
    ("success", "What does success look like in a month — time saved, errors avoided, a number?"),
    ("out_of_scope", "What is explicitly out of scope for v1?"),
)


class ToolRequestBrief(BaseModel):
    """The ten answers plus the two naming fields, as submitted by the form."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=200)
    slug_hint: str = Field(min_length=3, max_length=50, pattern=SLUG_PATTERN)

    users: str = Field(min_length=3, max_length=2000)
    decision: str = Field(min_length=10, max_length=2000)
    today: str = Field(min_length=3, max_length=2000)
    states: str = Field(min_length=10, max_length=2000)
    must_never_happen: str = Field(min_length=3, max_length=2000)
    provable: str = Field(min_length=3, max_length=2000)
    data_sources: str = Field(min_length=3, max_length=2000)
    volume: str = Field(min_length=1, max_length=2000)
    success: str = Field(min_length=3, max_length=2000)
    out_of_scope: str = Field(min_length=3, max_length=2000)

    @field_validator("slug_hint")
    @classmethod
    def _reserved_slug(cls, value: str) -> str:
        if value in RESERVED_SLUGS:
            raise ValueError(f"'{value}' is reserved; pick another name")
        return value


class ToolRequestCreate(ToolRequestBrief):
    requester_user_id: int
    status: str = STATUS_QUEUED


class ToolRequestDispatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    session_id: str | None = None
    session_url: str | None = None
    dispatch_error: str | None = None


class ToolRequestRead(ToolRequestBrief):
    #: Stored rows are read back with the pattern relaxed: tightening the accepted shape must not make an older
    #: request unreadable.
    slug_hint: str

    id: int
    requester_user_id: int
    status: str
    session_id: str | None
    session_url: str | None
    dispatch_error: str | None
    created_at: datetime
