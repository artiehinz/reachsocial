import hashlib
import importlib.util
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


installer = module(ROOT / "scripts/install_operations.py")
ops = module(ROOT / "deploy/operations/reachsocial-ops.py")
VERSION = "a" * 40


def test_restore_issuer_is_accepted_by_oauth_library():
    from mcp.server.auth.routes import validate_issuer_url
    from pydantic import AnyHttpUrl

    script = (ROOT / "scripts/verify_nightly_restore.sh").read_text()
    issuer = re.search(r"--env PUBLIC_BASE_URL=(\S+)", script).group(1)
    validate_issuer_url(AnyHttpUrl(issuer))


def bundle(extra=None):
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output, mode="w", format=tarfile.PAX_FORMAT, pax_headers={"comment": VERSION}
    ) as archive:
        for name in sorted(installer.FILES):
            data = (ROOT / name).read_bytes()
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        if extra:
            archive.addfile(extra)
    data = output.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def test_bundle_requires_approved_bytes_and_commit():
    data, digest = bundle()
    assert installer.approved_payload(data, VERSION, digest).keys() == installer.FILES
    with pytest.raises(ValueError, match="checksum"):
        installer.approved_payload(data + b"tampered", VERSION, digest)
    with pytest.raises(ValueError, match="commit"):
        installer.approved_payload(data, "b" * 40, digest)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../../etc/sudoers", tarfile.REGTYPE),
        ("scripts/backup_droplet.sh", tarfile.REGTYPE),
        ("scripts/evil", tarfile.SYMTYPE),
    ],
)
def test_archive_rejects_traversal_duplicates_and_links(name, kind):
    entry = tarfile.TarInfo(name)
    entry.type = kind
    entry.linkname = "/etc/sudoers"
    data, digest = bundle(entry)
    with pytest.raises(ValueError, match="Unexpected"):
        installer.approved_payload(data, VERSION, digest)


@pytest.mark.parametrize("args", [[], ["sh"], ["backup", "/tmp/evil"], ["backup;id"]])
def test_wrapper_rejects_unlisted_commands_and_extra_arguments(args):
    with pytest.raises(SystemExit, match="Usage"):
        ops.main(args)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    state, code = tmp_path / "state", tmp_path / "code"
    state.mkdir()
    code.mkdir()
    scripts = {}
    for name in ops.ACTIONS.values():
        data = b"#!/bin/bash\nexit 0\n"
        (code / name).write_bytes(data)
        scripts[name] = hashlib.sha256(data).hexdigest()
    (code / "manifest.json").write_text(json.dumps({"version": VERSION, "scripts": scripts}))
    monkeypatch.setattr(ops, "STATE", state)
    monkeypatch.setattr(ops, "CODE", code)
    monkeypatch.setattr(ops.os, "geteuid", lambda: 0)
    monkeypatch.setattr(ops.os.path, "ismount", lambda _: True)
    monkeypatch.setattr(ops.os, "umask", lambda _: None)
    return state, code


@pytest.mark.parametrize("returncode,status", [(0, "passed"), (1, "failed")])
def test_runs_only_fixed_script_with_clean_environment(
    installed, monkeypatch, capsys, returncode, status
):
    state, code = installed
    monkeypatch.setenv("BASH_ENV", "/tmp/evil")
    monkeypatch.setenv("RESTIC_REPOSITORY", "/tmp/evil")

    def run(args, **kwargs):
        assert args == ["/bin/bash", "--noprofile", "--norc", str(code / "backup_droplet.sh")]
        assert kwargs["env"] == ops.ENV
        assert "BASH_ENV" not in kwargs["env"]
        assert "RESTIC_REPOSITORY" not in kwargs["env"]
        assert kwargs["stdin"] == subprocess.DEVNULL
        kwargs["stdout"].write("private diagnostic\n")
        return subprocess.CompletedProcess(args, returncode)

    monkeypatch.setattr(ops.subprocess, "run", run)
    assert ops.main(["backup"]) == returncode
    assert json.loads((state / "backup.json").read_text())["status"] == status
    assert "private diagnostic" not in capsys.readouterr().out
    assert ops.main(["backup-status"]) == 0
    assert json.loads(capsys.readouterr().out)["backup"]["status"] == status


def test_modified_script_is_not_executed(installed):
    _, code = installed
    (code / "backup_droplet.sh").write_text("exit 0\n")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        ops.main(["backup"])


def test_missing_mount_and_nonroot_are_rejected(installed, monkeypatch):
    monkeypatch.setattr(ops.os.path, "ismount", lambda _: False)
    with pytest.raises(SystemExit, match="not mounted"):
        ops.main(["backup"])
    monkeypatch.setattr(ops.os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit, match="sudo"):
        ops.main(["backup"])


def test_operations_share_nonblocking_lock(installed):
    state, _ = installed
    with (state / "operations.lock").open("a") as lock:
        ops.fcntl.flock(lock, ops.fcntl.LOCK_EX)
        with pytest.raises(SystemExit, match="already running"):
            ops.main(["verify-restore"])


@pytest.mark.parametrize("reject_sudoers", [False, True])
def test_installer_validates_before_writes_and_preserves_rollback(
    tmp_path, monkeypatch, reject_sudoers
):
    state, code = tmp_path / "state", tmp_path / "code"
    targets = {
        source: (tmp_path / str(destination).lstrip("/"), mode)
        for source, (destination, mode) in installer.TARGETS.items()
    }
    for destination, _ in targets.values():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(destination))
    monkeypatch.setattr(installer, "STATE", state)
    monkeypatch.setattr(installer, "CODE", code)
    monkeypatch.setattr(installer, "TARGETS", targets)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installer.os.path, "ismount", lambda _: True)
    monkeypatch.setattr(installer.os, "umask", lambda _: None)
    # Exercise the installer without creating host files or requiring test sudo.
    monkeypatch.setattr(
        installer,
        "protected_directory",
        lambda path, mode: path.mkdir(parents=True, exist_ok=True, mode=mode),
    )

    def run(args, **kwargs):
        if args[:2] == ["/usr/sbin/visudo", "-cf"] and reject_sudoers:
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(installer.subprocess, "run", run)
    data, digest = bundle()
    archive = tmp_path / "bundle.tar"
    archive.write_bytes(data)
    if reject_sudoers:
        with pytest.raises(subprocess.CalledProcessError):
            installer.main([str(archive), VERSION, digest])
        for destination, _ in targets.values():
            assert destination.read_text() == str(destination)
        assert not (code / "manifest.json").exists()
    else:
        installer.main([str(archive), VERSION, digest])
        assert json.loads((code / "manifest.json").read_text())["version"] == VERSION
        for source, (destination, mode) in targets.items():
            assert destination.read_bytes() == (ROOT / source).read_bytes()
            assert destination.stat().st_mode & 0o777 == mode
            saved = state / "previous-install" / str(destination).lstrip("/")
            assert saved.read_text() == str(destination)
