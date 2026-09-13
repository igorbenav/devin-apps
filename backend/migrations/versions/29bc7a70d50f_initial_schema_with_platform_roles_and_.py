"""Initial schema: the boilerplate tables plus platform roles, role assignments and the audit log.

The boilerplate ships no migrations (tables are created on startup from the
models), so this is the baseline revision. Run it with
``CREATE_TABLES_ON_STARTUP=false`` so Alembic owns the schema.

Revision ID: 29bc7a70d50f
Revises:
Create Date: 2026-09-13 18:49:24.216348
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "29bc7a70d50f"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "platform_role",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_role")),
    )
    op.create_index(op.f("ix_platform_role_name"), "platform_role", ["name"], unique=True)
    op.create_table(
        "tiers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tiers")),
        sa.UniqueConstraint("name", name=op.f("uq_tiers_name")),
    )
    op.create_table(
        "rate_limits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tier_id"], ["tiers.id"], name=op.f("fk_rate_limits_tier_id_tiers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_limits")),
        sa.UniqueConstraint("name", name=op.f("uq_rate_limits_name")),
    )
    op.create_index(op.f("ix_rate_limits_tier_id"), "rate_limits", ["tier_id"], unique=False)
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=50), nullable=False),
        sa.Column("hashed_password", sa.String(length=100), nullable=False),
        sa.Column("profile_image_url", sa.String(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=True),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("google_id", sa.String(length=50), nullable=True),
        sa.Column("github_id", sa.String(length=50), nullable=True),
        sa.Column("oauth_provider", sa.String(length=20), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("oauth_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oauth_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tier_id"], ["tiers.id"], name=op.f("fk_user_tier_id_tiers")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)
    op.create_index(op.f("ix_user_github_id"), "user", ["github_id"], unique=True)
    op.create_index(op.f("ix_user_google_id"), "user", ["google_id"], unique=True)
    op.create_index(op.f("ix_user_tier_id"), "user", ["tier_id"], unique=False)
    op.create_index(op.f("ix_user_username"), "user", ["username"], unique=True)
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("permissions", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("usage_limits", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(length=45), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("key_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_api_keys_user_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index("idx_api_keys_expires_at", "api_keys", ["expires_at"], unique=False)
    op.create_index("idx_api_keys_prefix", "api_keys", ["key_prefix"], unique=False)
    op.create_index("idx_api_keys_user_active", "api_keys", ["user_id", "is_active"], unique=False)
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)
    op.create_table(
        "platform_audit_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user.id"], name=op.f("fk_platform_audit_event_actor_user_id_user"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_audit_event")),
    )
    op.create_index(op.f("ix_platform_audit_event_action"), "platform_audit_event", ["action"], unique=False)
    op.create_index(op.f("ix_platform_audit_event_actor_user_id"), "platform_audit_event", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_platform_audit_event_entity_id"), "platform_audit_event", ["entity_id"], unique=False)
    op.create_index(op.f("ix_platform_audit_event_entity_type"), "platform_audit_event", ["entity_type"], unique=False)
    op.create_index(op.f("ix_platform_audit_event_occurred_at"), "platform_audit_event", ["occurred_at"], unique=False)
    op.create_table(
        "platform_user_role",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["role_id"], ["platform_role.id"], name=op.f("fk_platform_user_role_role_id_platform_role"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_platform_user_role_user_id_user"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_user_role")),
        sa.UniqueConstraint("user_id", "role_id", name="uq_platform_user_role_user_id_role_id"),
    )
    op.create_index(op.f("ix_platform_user_role_role_id"), "platform_user_role", ["role_id"], unique=False)
    op.create_index(op.f("ix_platform_user_role_user_id"), "platform_user_role", ["user_id"], unique=False)
    op.create_table(
        "key_permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column(
            "resource",
            sa.Enum(
                "CONVERSATIONS",
                "CREDITS",
                "AI_USAGE",
                "USER_PROFILE",
                "ANALYTICS",
                "ADMIN",
                "BILLING",
                "API_KEYS",
                "WILDCARD",
                name="keypermissionresource",
            ),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.Enum("READ", "WRITE", "DELETE", "CREATE", "UPDATE", "LIST", "ADMIN", "WILDCARD", name="keypermissionaction"),
            nullable=False,
        ),
        sa.Column("conditions", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["api_keys.id"], name=op.f("fk_key_permissions_api_key_id_api_keys"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_key_permissions")),
    )
    op.create_index("idx_key_permissions_key_resource", "key_permissions", ["api_key_id", "resource", "action"], unique=True)
    op.create_index("idx_key_permissions_resource_action", "key_permissions", ["resource", "action"], unique=False)
    op.create_index(op.f("ix_key_permissions_action"), "key_permissions", ["action"], unique=False)
    op.create_index(op.f("ix_key_permissions_api_key_id"), "key_permissions", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_key_permissions_resource"), "key_permissions", ["resource"], unique=False)
    op.create_table(
        "key_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("cost_microcents", sa.BigInteger(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("usage_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["api_keys.id"], name=op.f("fk_key_usage_api_key_id_api_keys"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_key_usage_user_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_key_usage")),
    )
    op.create_index("idx_key_usage_endpoint", "key_usage", ["endpoint"], unique=False)
    op.create_index("idx_key_usage_key_created", "key_usage", ["api_key_id", "created_at"], unique=False)
    op.create_index("idx_key_usage_status", "key_usage", ["status_code"], unique=False)
    op.create_index("idx_key_usage_user_created", "key_usage", ["user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_key_usage_api_key_id"), "key_usage", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_key_usage_user_id"), "key_usage", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_key_usage_user_id"), table_name="key_usage")
    op.drop_index(op.f("ix_key_usage_api_key_id"), table_name="key_usage")
    op.drop_index("idx_key_usage_user_created", table_name="key_usage")
    op.drop_index("idx_key_usage_status", table_name="key_usage")
    op.drop_index("idx_key_usage_key_created", table_name="key_usage")
    op.drop_index("idx_key_usage_endpoint", table_name="key_usage")
    op.drop_table("key_usage")
    op.drop_index(op.f("ix_key_permissions_resource"), table_name="key_permissions")
    op.drop_index(op.f("ix_key_permissions_api_key_id"), table_name="key_permissions")
    op.drop_index(op.f("ix_key_permissions_action"), table_name="key_permissions")
    op.drop_index("idx_key_permissions_resource_action", table_name="key_permissions")
    op.drop_index("idx_key_permissions_key_resource", table_name="key_permissions")
    op.drop_table("key_permissions")
    op.drop_index(op.f("ix_platform_user_role_user_id"), table_name="platform_user_role")
    op.drop_index(op.f("ix_platform_user_role_role_id"), table_name="platform_user_role")
    op.drop_table("platform_user_role")
    op.drop_index(op.f("ix_platform_audit_event_occurred_at"), table_name="platform_audit_event")
    op.drop_index(op.f("ix_platform_audit_event_entity_type"), table_name="platform_audit_event")
    op.drop_index(op.f("ix_platform_audit_event_entity_id"), table_name="platform_audit_event")
    op.drop_index(op.f("ix_platform_audit_event_actor_user_id"), table_name="platform_audit_event")
    op.drop_index(op.f("ix_platform_audit_event_action"), table_name="platform_audit_event")
    op.drop_table("platform_audit_event")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_index("idx_api_keys_user_active", table_name="api_keys")
    op.drop_index("idx_api_keys_prefix", table_name="api_keys")
    op.drop_index("idx_api_keys_expires_at", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_user_username"), table_name="user")
    op.drop_index(op.f("ix_user_tier_id"), table_name="user")
    op.drop_index(op.f("ix_user_google_id"), table_name="user")
    op.drop_index(op.f("ix_user_github_id"), table_name="user")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
    op.drop_index(op.f("ix_rate_limits_tier_id"), table_name="rate_limits")
    op.drop_table("rate_limits")
    op.drop_table("tiers")
    op.drop_index(op.f("ix_platform_role_name"), table_name="platform_role")
    op.drop_table("platform_role")
