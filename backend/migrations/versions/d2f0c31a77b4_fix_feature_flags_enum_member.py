"""Add the FEATURE_FLAGS enum member under the name SQLAlchemy writes.

Revision ID: d2f0c31a77b4
Revises: c41ab0d7e5f2
Create Date: 2026-09-13

``keypermissionresource`` stores enum member names ("CONVERSATIONS", …), but
c41ab0d7e5f2 added the member's value ("feature_flags"), so inserting a
feature-flag key permission failed with an invalid enum input.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2f0c31a77b4"
down_revision: str | Sequence[str] | None = "c41ab0d7e5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE keypermissionresource ADD VALUE IF NOT EXISTS 'FEATURE_FLAGS'")


def downgrade() -> None:
    """Postgres cannot drop a value from an enum type; the extra value is harmless."""
