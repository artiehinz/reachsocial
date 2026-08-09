"""Prune durable operational records older than the configured retention period."""

from __future__ import annotations

from reachsocial.db import init_db
from reachsocial.maintenance import prune_operational_records


def main() -> None:
    init_db()
    counts = prune_operational_records()
    print("Retention maintenance: " + " ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
