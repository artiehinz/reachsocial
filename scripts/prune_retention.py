"""Prune durable operational records older than the configured retention period."""

from __future__ import annotations

from reachsocial.db import init_db
from reachsocial.maintenance import prune_operational_records


def main() -> None:
    init_db()
    deleted_requests, deleted_idempotency = prune_operational_records()
    print(
        f"Deleted {deleted_requests} requests and {deleted_idempotency} expired idempotency records"
    )


if __name__ == "__main__":
    main()
