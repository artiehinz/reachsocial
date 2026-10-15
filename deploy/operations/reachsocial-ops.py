#!/usr/bin/python3 -I
"""Fixed root operations; no caller environment, paths, or script arguments."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VOLUME = Path("/mnt/reachsocial_data_tor1_01")
STATE = VOLUME / "operations/reachsocial-ops"
CODE = Path("/usr/local/lib/reachsocial-ops")
ACTIONS = {"backup": "backup_droplet.sh", "verify-restore": "verify_nightly_restore.sh"}
ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "LANG": "C.UTF-8",
    "RESTIC_CACHE_DIR": str(STATE / "cache"),
    "TMPDIR": str(STATE / "tmp"),
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save_status(action, record):
    temporary = STATE / f"{action}.json.tmp"
    temporary.write_text(json.dumps(record) + "\n")
    temporary.replace(STATE / f"{action}.json")


def main(args):
    if len(args) != 1 or args[0] not in {*ACTIONS, "backup-status"}:
        raise SystemExit("Usage: reachsocial-ops {backup|verify-restore|backup-status}")
    if os.geteuid() != 0:
        raise SystemExit("Use sudo with the installed fixed-action command.")
    if not os.path.ismount(VOLUME):
        raise SystemExit("Production volume is not mounted; refusing operations.")
    os.umask(0o077)
    action = args[0]
    # Shared with the installer so a run never mixes approved script versions.
    with (STATE / "operations.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("An operation or installation is already running.") from None
        manifest = json.loads((CODE / "manifest.json").read_text())
        if action == "backup-status":
            result = {"version": manifest["version"]}
            for name in ACTIONS:
                path = STATE / f"{name}.json"
                result[name] = json.loads(path.read_text()) if path.exists() else None
            print(json.dumps(result, indent=2))
            return 0
        script = CODE / ACTIONS[action]
        if hashlib.sha256(script.read_bytes()).hexdigest() != manifest["scripts"][script.name]:
            raise SystemExit("Installed script checksum mismatch; refusing operations.")
        record = {"version": manifest["version"], "started_at": timestamp(), "status": "running"}
        save_status(action, record)
        # Logs may contain restored database errors. Only root can read them;
        # callers receive completion metadata, never database or environment text.
        with (STATE / f"{action}.log").open("w") as log:
            try:
                completed = subprocess.run(
                    ["/bin/bash", "--noprofile", "--norc", str(script)],
                    cwd=STATE,
                    env=ENV,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                code = completed.returncode
            except OSError:
                code = 1
        record.update(
            completed_at=timestamp(), status="passed" if code == 0 else "failed", exit_code=code
        )
        save_status(action, record)
        print(json.dumps({action: record}))
        return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
