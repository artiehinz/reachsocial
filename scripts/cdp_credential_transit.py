#!/usr/bin/env python3
"""Stage a replacement CDP API key pair for one-time runtime installation."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import stat
import time
from pathlib import Path

STAGING_FILE = Path(
    "/mnt/instaget-nvme/herald-work/.private-transit/cdp-runtime-credentials.json"
)


def validate(value: str, label: str) -> str:
    if not value or value.isspace() or "\n" in value or "\r" in value:
        raise ValueError(f"{label} must be a non-empty single-line value")
    return value


def stage(key_id: str, key_secret: str, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination.parent, stat.S_IRWXU)
    if destination.exists():
        raise FileExistsError("an unconsumed credential transit already exists")
    temporary = destination.with_suffix(".tmp")
    payload = json.dumps({"CDP_API_KEY_ID": key_id, "CDP_API_KEY_SECRET": key_secret})
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expires-in-minutes", type=int, default=10)
    parser.add_argument("--confirm-stage-cdp-credentials", action="store_true")
    args = parser.parse_args()
    if not args.confirm_stage_cdp_credentials:
        parser.error("--confirm-stage-cdp-credentials is required")
    if not 1 <= args.expires_in_minutes <= 30:
        parser.error("--expires-in-minutes must be between 1 and 30")

    try:
        key_id = validate(getpass.getpass("Paste the new CDP API key ID (input is hidden): "), "ID")
        key_secret = validate(
            getpass.getpass("Paste the new CDP API key secret (input is hidden): "), "secret"
        )
        stage(key_id, key_secret, STAGING_FILE)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    def remove_staged(_signal: int, _frame: object) -> None:
        STAGING_FILE.unlink(missing_ok=True)
        raise SystemExit(1)

    signal.signal(signal.SIGHUP, remove_staged)
    signal.signal(signal.SIGINT, remove_staged)
    deadline = time.monotonic() + args.expires_in_minutes * 60
    print("CDP credentials staged for one-time installation; no values were displayed.")
    print("Keep this terminal open until the transit is consumed or expires.")
    try:
        while STAGING_FILE.exists() and time.monotonic() < deadline:
            time.sleep(1)
    finally:
        if STAGING_FILE.exists():
            STAGING_FILE.unlink()
            print("CDP credential transit expired and was deleted.")
        else:
            print("CDP credential transit consumed and deleted.")


if __name__ == "__main__":
    main()
