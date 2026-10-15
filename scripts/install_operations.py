#!/usr/bin/python3 -I
"""Root-console installer for an owner-approved git archive and SHA-256."""

import fcntl
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

VOLUME = Path("/mnt/reachsocial_data_tor1_01")
STATE = VOLUME / "operations/reachsocial-ops"
CODE = Path("/usr/local/lib/reachsocial-ops")
FILES = {
    "deploy/operations/reachsocial-ops.py",
    "deploy/operations/sudoers",
    "deploy/operations/cron",
    "scripts/backup_droplet.sh",
    "scripts/verify_nightly_restore.sh",
}
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8"}
TARGETS = {
    "deploy/operations/sudoers": (Path("/etc/sudoers.d/reachsocial-ops"), 0o440),
    "deploy/operations/cron": (Path("/etc/cron.d/reachsocial-backup"), 0o644),
    "deploy/operations/reachsocial-ops.py": (Path("/usr/local/sbin/reachsocial-ops"), 0o755),
}


def approved_payload(bundle, version, checksum):
    if not re.fullmatch(r"[0-9a-f]{40}", version):
        raise ValueError("Approval must name a full commit SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Approval must name a SHA-256 checksum")
    # Verify the exact bytes later consumed, avoiding a staged-file replacement race.
    if hashlib.sha256(bundle).hexdigest() != checksum:
        raise ValueError("Bundle checksum does not match owner approval")
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:") as archive:
        if archive.pax_headers.get("comment") != version:
            raise ValueError("Bundle commit does not match owner approval")
        payload = {}
        for entry in archive:
            if entry.isdir() and entry.name in {"deploy", "deploy/operations", "scripts"}:
                continue
            if not entry.isfile() or entry.name not in FILES or entry.name in payload:
                raise ValueError("Unexpected bundle member")
            payload[entry.name] = archive.extractfile(entry).read()
        if payload.keys() != FILES:
            raise ValueError("Incomplete operations bundle")
        return payload


def protected_directory(path, mode=0o755):
    if path != path.parent:
        protected_directory(path.parent)
    if not path.exists():
        path.mkdir(mode=mode)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"Directory must be root-owned and not group/world writable: {path}")


def atomic_write(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix=".operations-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            os.fchmod(output.fileno(), mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(args):
    if len(args) != 3:
        raise SystemExit("Usage: install_operations.py BUNDLE APPROVED_COMMIT APPROVED_SHA256")
    if os.geteuid() != 0 or not os.path.ismount(VOLUME):
        raise SystemExit("Run in the root console with the production volume mounted.")
    bundle, version, checksum = args
    payload = approved_payload(Path(bundle).read_bytes(), version, checksum)
    subprocess.run(["/usr/sbin/visudo", "-c"], env=ENV, check=True)
    os.umask(0o077)
    for path in (
        STATE,
        STATE / "tmp",
        STATE / "cache",
        CODE,
        *(destination.parent for destination, _ in TARGETS.values()),
    ):
        protected_directory(path, 0o700 if path.is_relative_to(STATE) else 0o755)
    if STATE.stat().st_mode & 0o077:
        raise ValueError("Operations state must be accessible only to root")
    with (STATE / "operations.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix="install-", dir=STATE) as temporary:
            stage = Path(temporary)
            for name, data in payload.items():
                (stage / Path(name).name).write_bytes(data)
            subprocess.run(["/usr/sbin/visudo", "-cf", str(stage / "sudoers")], env=ENV, check=True)
            subprocess.run(
                ["/bin/bash", "-n", str(stage / "backup_droplet.sh")], env=ENV, check=True
            )
            subprocess.run(
                ["/bin/bash", "-n", str(stage / "verify_nightly_restore.sh")], env=ENV, check=True
            )
            compile(payload["deploy/operations/reachsocial-ops.py"], "reachsocial-ops", "exec")
            # Preserve the previous privileged configuration for console rollback.
            previous = STATE / "previous-install"
            if previous.exists():
                raise ValueError(
                    "Archive previous-install in the root console before another update"
                )
            previous.mkdir(mode=0o700)
            destinations = {
                destination: (payload[source], mode)
                for source, (destination, mode) in TARGETS.items()
            }
            manifest = {"version": version, "bundle_sha256": checksum, "scripts": {}}
            for name in ("backup_droplet.sh", "verify_nightly_restore.sh"):
                data = payload[f"scripts/{name}"]
                destinations[CODE / name] = (data, 0o700)
                manifest["scripts"][name] = hashlib.sha256(data).hexdigest()
            destinations[CODE / "manifest.json"] = ((json.dumps(manifest) + "\n").encode(), 0o644)
            for destination in destinations:
                if destination.is_symlink():
                    raise ValueError(f"Refusing symlink destination: {destination}")
                if destination.exists():
                    saved = previous / str(destination).lstrip("/")
                    saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    atomic_write(saved, destination.read_bytes(), 0o600)
            # Install code before enabling sudo and cron.
            for destination in sorted(destinations, key=lambda p: str(p).startswith("/etc/")):
                data, mode = destinations[destination]
                atomic_write(destination, data, mode)
        subprocess.run(["/usr/sbin/visudo", "-c"], env=ENV, check=True)
    print(f"Installed approved operations version {version}")


if __name__ == "__main__":
    main(sys.argv[1:])
