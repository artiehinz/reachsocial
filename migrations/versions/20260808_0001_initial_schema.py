"""Initial ReachSocial schema.

Revision ID: 20260808_0001
Revises:
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260808_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("api_key_hash", sa.String(256), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("billing_mode", sa.String(30), nullable=False, server_default="internal"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("daily_spend_cents", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_clients_name", "clients", ["name"], unique=True)
    op.create_index("ix_clients_api_key_hash", "clients", ["api_key_hash"], unique=True)
    op.create_index("ix_clients_status", "clients", ["status"])

    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_services_service_id", "services", ["service_id"], unique=True)

    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id")),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("upstream_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("charged_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_requests_request_id", "requests", ["request_id"], unique=True)
    op.create_index("ix_requests_client_id", "requests", ["client_id"])
    op.create_index("ix_requests_service_id", "requests", ["service_id"])
    op.create_index("ix_requests_status", "requests", ["status"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_idempotency_records_client_id", "idempotency_records", ["client_id"])
    op.create_index("ix_idempotency_records_service_id", "idempotency_records", ["service_id"])
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])

    op.create_table(
        "payment_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.String(255), nullable=False),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_payment_receipts_payment_id", "payment_receipts", ["payment_id"], unique=True
    )
    op.create_index("ix_payment_receipts_service_id", "payment_receipts", ["service_id"])
    op.create_index("ix_payment_receipts_status", "payment_receipts", ["status"])


def downgrade() -> None:
    op.drop_table("payment_receipts")
    op.drop_table("idempotency_records")
    op.drop_table("requests")
    op.drop_table("services")
    op.drop_table("clients")
