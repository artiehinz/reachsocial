from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from reachsocial.config import get_settings


def test_existing_database_upgrades_and_schema_downgrades(tmp_path, monkeypatch) -> None:
    database = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "20260808_0001")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO clients "
                "(name, api_key_hash, status, billing_mode, rate_limit_per_minute, "
                "concurrency_limit, daily_spend_cents) "
                "VALUES ('existing', 'hash', 'active', 'internal', 30, 2, 5000)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO payment_receipts "
                "(payment_id, service_id, amount_cents, network, status) "
                "VALUES ('payment-existing', 'instagram.profile', 5, 'eip155:84532', 'settled')"
            )
        )
    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert {
        "async_jobs",
        "client_services",
        "provider_attempts",
        "public_test_usage",
        "service_credits",
        "mainnet_canary_attempts",
    }.issubset(set(inspector.get_table_names()))
    assert "key_id" in {column["name"] for column in inspector.get_columns("clients")}
    indexes = {item["name"]: item for item in inspector.get_indexes("idempotency_records")}
    assert indexes["uq_idempotency_records_client_service_key"]["unique"] == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM clients")) == "existing"
        assert connection.scalar(
            text("SELECT updated_at FROM payment_receipts WHERE payment_id='payment-existing'")
        ) is not None
    command.downgrade(config, "20260808_0001")
    inspector = inspect(engine)
    assert "async_jobs" not in inspector.get_table_names()
    assert "key_id" not in {column["name"] for column in inspector.get_columns("clients")}
    get_settings.cache_clear()


def test_partial_sqlite_migration_can_resume(tmp_path, monkeypatch) -> None:
    database = tmp_path / "partial-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "20260808_0001")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE clients ADD COLUMN key_id VARCHAR(32)"))
        connection.execute(
            text("ALTER TABLE clients ADD COLUMN api_key_expires_at DATETIME")
        )
        connection.execute(text("ALTER TABLE clients ADD COLUMN rotated_at DATETIME"))
        connection.execute(text("CREATE UNIQUE INDEX ix_clients_key_id ON clients (key_id)"))
        connection.execute(
            text(
                "INSERT INTO payment_receipts "
                "(payment_id, service_id, amount_cents, network, status) "
                "VALUES ('payment-partial', 'instagram.post', 5, 'eip155:84532', 'verified')"
            )
        )

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "provider_attempts" in inspector.get_table_names()
    assert "updated_at" in {
        column["name"] for column in inspector.get_columns("payment_receipts")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261014_0005"
        assert connection.scalar(
            text("SELECT updated_at FROM payment_receipts WHERE payment_id='payment-partial'")
        ) is not None
    assert "provider_credit_reservations" in inspector.get_table_names()
    get_settings.cache_clear()
