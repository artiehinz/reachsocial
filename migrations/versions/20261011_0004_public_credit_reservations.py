"""Add durable ScrapeCreators capacity reservations for public payments.

Revision ID: 20261011_0004
Revises: 20261011_0003
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0004"
down_revision = "20261011_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credit_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("service_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reserved_units", sa.Integer(), nullable=False),
        sa.Column("consumed_units", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_credit_reservations_payment_id",
        "provider_credit_reservations",
        ["payment_id"],
        unique=True,
    )
    op.create_index(
        "ix_provider_credit_reservations_provider",
        "provider_credit_reservations",
        ["provider"],
    )
    op.create_index(
        "ix_provider_credit_reservations_service_id",
        "provider_credit_reservations",
        ["service_id"],
    )
    op.create_index(
        "ix_provider_credit_reservations_status",
        "provider_credit_reservations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("provider_credit_reservations")
