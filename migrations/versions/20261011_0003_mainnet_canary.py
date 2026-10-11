"""Add the one-time Base-mainnet canary reservation.

Revision ID: 20261011_0003
Revises: 20260809_0002
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0003"
down_revision = "20260809_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mainnet_canary_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("canary_key", sa.String(length=120), nullable=False),
        sa.Column("payment_id", sa.String(length=255), nullable=False),
        sa.Column("payer", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mainnet_canary_attempts_canary_key",
        "mainnet_canary_attempts",
        ["canary_key"],
        unique=True,
    )
    op.create_index(
        "ix_mainnet_canary_attempts_payment_id",
        "mainnet_canary_attempts",
        ["payment_id"],
        unique=True,
    )
    op.create_index(
        "ix_mainnet_canary_attempts_payer", "mainnet_canary_attempts", ["payer"]
    )
    op.create_index(
        "ix_mainnet_canary_attempts_status", "mainnet_canary_attempts", ["status"]
    )


def downgrade() -> None:
    op.drop_table("mainnet_canary_attempts")
