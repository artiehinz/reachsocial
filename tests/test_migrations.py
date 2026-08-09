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
    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert {
        "async_jobs",
        "client_services",
        "provider_attempts",
        "public_test_usage",
        "service_credits",
    }.issubset(set(inspector.get_table_names()))
    assert "key_id" in {column["name"] for column in inspector.get_columns("clients")}
    indexes = {item["name"]: item for item in inspector.get_indexes("idempotency_records")}
    assert indexes["uq_idempotency_records_client_service_key"]["unique"] == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM clients")) == "existing"
    command.downgrade(config, "20260808_0001")
    inspector = inspect(engine)
    assert "async_jobs" not in inspector.get_table_names()
    assert "key_id" not in {column["name"] for column in inspector.get_columns("clients")}
    get_settings.cache_clear()
