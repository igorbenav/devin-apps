"""Add the KYC review queue tables.

Cases reference ``user`` for their assignee and decider; both are ``SET NULL``
so deleting a user never deletes review history. Documents cascade with their
case — they hold filenames only, nothing is stored.

Revision ID: b5a78fcfe4da
Revises: 29bc7a70d50f
Create Date: 2026-09-13 19:38:43.360135
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5a78fcfe4da"
down_revision: str | Sequence[str] | None = "29bc7a70d50f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "kyc_case",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_ref", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_to"], ["user.id"], name=op.f("fk_kyc_case_assigned_to_user"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["user.id"], name=op.f("fk_kyc_case_decided_by_user"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_case")),
    )
    op.create_index(op.f("ix_kyc_case_assigned_to"), "kyc_case", ["assigned_to"], unique=False)
    op.create_index(op.f("ix_kyc_case_customer_ref"), "kyc_case", ["customer_ref"], unique=False)
    op.create_index(op.f("ix_kyc_case_risk_score"), "kyc_case", ["risk_score"], unique=False)
    op.create_index(op.f("ix_kyc_case_state"), "kyc_case", ["state"], unique=False)
    op.create_index(op.f("ix_kyc_case_submitted_at"), "kyc_case", ["submitted_at"], unique=False)
    op.create_table(
        "kyc_document",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"], ["kyc_case.id"], name=op.f("fk_kyc_document_case_id_kyc_case"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_document")),
    )
    op.create_index(op.f("ix_kyc_document_case_id"), "kyc_document", ["case_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_kyc_document_case_id"), table_name="kyc_document")
    op.drop_table("kyc_document")
    op.drop_index(op.f("ix_kyc_case_submitted_at"), table_name="kyc_case")
    op.drop_index(op.f("ix_kyc_case_state"), table_name="kyc_case")
    op.drop_index(op.f("ix_kyc_case_risk_score"), table_name="kyc_case")
    op.drop_index(op.f("ix_kyc_case_customer_ref"), table_name="kyc_case")
    op.drop_index(op.f("ix_kyc_case_assigned_to"), table_name="kyc_case")
    op.drop_table("kyc_case")
