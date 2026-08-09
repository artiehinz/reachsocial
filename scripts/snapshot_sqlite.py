"""Create a bounded same-volume SQLite snapshot before a schema deployment."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from reachsocial.config import get_settings


def main() -> None:
    database_url = get_settings().database_url
    if not database_url.startswith("sqlite:///"):
        print("Pre-deploy SQLite snapshot skipped for non-SQLite database")
        return
    source = Path(database_url.removeprefix("sqlite:///"))
    if not source.exists():
        print("Pre-deploy SQLite snapshot skipped because the database does not exist yet")
        return
    snapshots = source.parent / "predeploy-snapshots"
    snapshots.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = snapshots / f"reachsocial-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    target.chmod(0o600)
    retained = sorted(snapshots.glob("reachsocial-*.db"), reverse=True)
    for old in retained[3:]:
        old.unlink()
    print(f"Created pre-deploy SQLite snapshot {target.name}")


if __name__ == "__main__":
    main()
