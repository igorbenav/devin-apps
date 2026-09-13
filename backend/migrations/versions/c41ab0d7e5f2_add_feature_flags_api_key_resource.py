"""Add the feature_flags API key permission resource.

Revision ID: c41ab0d7e5f2
Revises: 67196370bc66
Create Date: 2026-09-13

Scopes the flag evaluation key to its own resource instead of the wildcard.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c41ab0d7e5f2"
down_revision: str | Sequence[str] | None = "67196370bc66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE keypermissionresource ADD VALUE IF NOT EXISTS 'feature_flags'")


def downgrade() -> None:
    """Postgres cannot drop a value from an enum type; the extra value is harmless."""
