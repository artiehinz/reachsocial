"""Add normalized billing, entitlements, jobs, and credits.

Revision ID: 20260809_0002
Revises: 20260808_0001
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op

revision = "20260809_0002"
down_revision = "20260808_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("key_id", sa.String(32), nullable=True))
    op.add_column("clients", sa.Column("api_key_expires_at", sa.DateTime(timezone=True)))
    op.add_column("clients", sa.Column("rotated_at", sa.DateTime(timezone=True)))
    op.create_index("ix_clients_key_id", "clients", ["key_id"], unique=True)

    op.execute(
        "DELETE FROM idempotency_records WHERE id NOT IN "
        "(SELECT MAX(id) FROM idempotency_records GROUP BY client_id, service_id, key)"
    )
    op.create_index(
        "uq_idempotency_records_client_service_key",
        "idempotency_records",
        ["client_id", "service_id", "key"],
        unique=True,
    )

    for name in (
        "upstream_cost_microusd",
        "provider_units",
        "provider_unit_cost_microusd",
        "price_snapshot_cents",
    ):
        op.add_column(
            "requests", sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        )
    op.add_column("requests", sa.Column("provider_reference", sa.String(255)))

    op.add_column("payment_receipts", sa.Column("payer", sa.String(120)))
    op.add_column("payment_receipts", sa.Column("transaction", sa.String(255)))
    op.add_column("payment_receipts", sa.Column("request_id", sa.String(40)))
    op.add_column("payment_receipts", sa.Column("job_id", sa.String(40)))
    op.add_column(
        "payment_receipts",
        sa.Column("replacement_credit_cents", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "payment_receipts",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_payment_receipts_payer", "payment_receipts", ["payer"])
    op.create_index("ix_payment_receipts_transaction", "payment_receipts", ["transaction"])
    op.create_index("ix_payment_receipts_request_id", "payment_receipts", ["request_id"])
    op.create_index("ix_payment_receipts_job_id", "payment_receipts", ["job_id"])

    op.create_table(
        "client_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("client_id", "service_id"),
    )
    op.create_index("ix_client_services_client_id", "client_services", ["client_id"])
    op.create_index("ix_client_services_service_id", "client_services", ["service_id"])

    op.create_table(
        "async_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(40), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id")),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_token_hash", sa.String(256)),
        sa.Column("payment_id", sa.String(255)),
        sa.Column("price_snapshot_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_unit_cost_microusd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upstream_cost_microusd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reserved_upstream_cost_microusd",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("provider_reference", sa.String(255)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credit_claimed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("client_id", "service_id", "idempotency_key"),
    )
    for column in ("job_id", "client_id", "service_id", "status", "input_hash", "payment_id", "expires_at"):
        op.create_index(
            f"ix_async_jobs_{column}", "async_jobs", [column], unique=column == "job_id"
        )

    op.create_table(
        "service_credits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credit_id", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(256), nullable=False),
        sa.Column("job_id", sa.String(40), nullable=False),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("credit_id", "token_hash", "job_id", "service_id", "status", "expires_at"):
        op.create_index(
            f"ix_service_credits_{column}",
            "service_credits",
            [column],
            unique=column in {"credit_id", "token_hash"},
        )

    op.create_table(
        "provider_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(40)),
        sa.Column("job_id", sa.String(40)),
        sa.Column("service_id", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_reference", sa.String(255)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_unit_cost_microusd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upstream_cost_microusd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("public_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("request_id", "job_id", "service_id", "provider", "status", "public_test"):
        op.create_index(f"ix_provider_attempts_{column}", "provider_attempts", [column])

    op.create_table(
        "public_test_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usage_day", sa.String(10), nullable=False),
        sa.Column("identity_kind", sa.String(20), nullable=False),
        sa.Column("identity_hash", sa.String(128), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("usage_day", "identity_kind", "identity_hash"),
    )
    for column in ("usage_day", "identity_kind", "identity_hash"):
        op.create_index(f"ix_public_test_usage_{column}", "public_test_usage", [column])


def downgrade() -> None:
    op.drop_table("public_test_usage")
    op.drop_table("provider_attempts")
    op.drop_table("service_credits")
    op.drop_table("async_jobs")
    op.drop_table("client_services")
    op.drop_index(
        "uq_idempotency_records_client_service_key", table_name="idempotency_records"
    )

    for index in (
        "ix_payment_receipts_job_id",
        "ix_payment_receipts_request_id",
        "ix_payment_receipts_transaction",
        "ix_payment_receipts_payer",
    ):
        op.drop_index(index, table_name="payment_receipts")
    for name in (
        "updated_at",
        "replacement_credit_cents",
        "job_id",
        "request_id",
        "transaction",
        "payer",
    ):
        op.drop_column("payment_receipts", name)

    for name in (
        "provider_reference",
        "price_snapshot_cents",
        "provider_unit_cost_microusd",
        "provider_units",
        "upstream_cost_microusd",
    ):
        op.drop_column("requests", name)

    op.drop_index("ix_clients_key_id", table_name="clients")
    op.drop_column("clients", "rotated_at")
    op.drop_column("clients", "api_key_expires_at")
    op.drop_column("clients", "key_id")
