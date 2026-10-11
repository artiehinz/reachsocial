#!/usr/bin/env python3
"""Change only the public-payment pause flag in a protected runtime env file."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--pause", action="store_true")
    command.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    path = args.env_file
    source = path.read_text(encoding="utf-8")
    value = "true" if args.pause else "false"
    replacement = f"PUBLIC_PAYMENTS_PAUSED={value}"
    if re.search(r"(?m)^PUBLIC_PAYMENTS_PAUSED=.*$", source):
        updated = re.sub(r"(?m)^PUBLIC_PAYMENTS_PAUSED=.*$", replacement, source)
    else:
        updated = source.rstrip("\n") + "\n" + replacement + "\n"
    mode = path.stat().st_mode & 0o777
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"PUBLIC_PAYMENTS_PAUSED={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
