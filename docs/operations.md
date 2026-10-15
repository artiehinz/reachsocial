# ReachSocial operations and recovery

## Access and locations

| Location | Available access | Routine work |
| --- | --- | --- |
| Herald | Local checkout, GitHub CLI, existing deployment SSH key | Edit, test, commit, push private application repo; follow CI; check public health |
| Droplet, `reachsocial` | SSH key, Docker group; three installed sudo actions | Deploy through GitHub CI, inspect image/health, backup and rehearse restore |
| Droplet, root Recovery Console | Owner's password manager and DigitalOcean account | Initial wrapper installation, approved privileged script updates, exceptional recovery |

Herald checkout: `/mnt/instaget-nvme/herald-work/reachsocial` (also available at
`/home/herald/Desktop/reachsocial`). Local builds and artifacts stay on NVMe.
Droplet: `138.197.154.48`, DigitalOcean ID `590965709`; application directory:
`/mnt/reachsocial_data_tor1_01/apps/reachsocial`. Do not run host operations on Herald.
Never substitute the separate public client-documentation repository for the
private `artiehinz/reachsocial` application repository.

The existing Docker group is root-equivalent access. This workflow limits the
sudo interface and prevents accidental execution of mutable application scripts
as root; it does not sandbox a compromised Docker administrator. Do not use
Docker host mounts to bypass root-console approval. Removing Docker privilege
would require a separate deployment-access redesign.

Wallet payments, exceptional account recovery, and privileged-access changes
remain owner decisions. No payment or provider call is part of these operations.

## Routine commands

On Herald, run the locked checks in `AGENTS.md`, commit reviewed changes, then
push `main` to the private application repository. GitHub CI continues to deploy
the exact successful commit with the `reachsocial` SSH account. Follow the
`CI` and `Deploy production` runs using `gh run list --repo artiehinz/reachsocial`
and `gh run watch RUN_ID --repo artiehinz/reachsocial`.

```bash
# Herald: connect with the existing key and pinned host key.
ssh -i ~/.ssh/reachsocial_deploy -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes reachsocial@138.197.154.48
```

Run these on the Droplet as `reachsocial`:

```bash
curl --fail --silent --show-error https://reachsocial.dev/healthz
docker inspect --format '{{.Config.Image}}' reachsocial-app-1
sudo -n /usr/local/sbin/reachsocial-ops backup
sudo -n /usr/local/sbin/reachsocial-ops verify-restore
sudo -n /usr/local/sbin/reachsocial-ops backup-status
```

Compare the running image tag to the full deployed commit SHA. Backup and restore
return JSON with version, timestamps, status, and exit code. Status reports the
last run of each action; `null` means no run through this wrapper. A leftover
`running` record indicates an unfinished/interrupted run, never success.
The shared nonblocking lock rejects overlapping operations and installation.

Nightly backup remains at 08:17 UTC, using the same wrapper. It creates consistent
SQLite/PostgreSQL artifacts, encrypts them in Restic, applies the existing
retention policy, checks the repository, then updates the app's completion marker.
The weekly DigitalOcean volume snapshot workflow is unchanged. A same-volume
Restic backup alone does not establish off-host disaster recovery.

Restore verification selects the latest snapshot for the production host and
staging path. It checks SQLite integrity, required OAuth/request/payment tables,
and historical receipts; starts the exact local ReachSocial image with payments
disabled and no network; verifies health, OAuth metadata, and the MCP challenge;
then restores the AEU dump using the exact live PostgreSQL image with no network.
TCP readiness avoids the temporary PostgreSQL initialization server. Temporary
containers and restored files are removed on normal completion or script error.
SIGKILL or host failure can require owner cleanup of leftover rehearsal state.
This rehearsal never replaces the production databases.

Root-only logs and completion records are under
`/mnt/reachsocial_data_tor1_01/operations/reachsocial-ops/`. The caller receives
metadata only. A failed run requires reviewing its protected `backup.log` or
`verify-restore.log` through the console; never paste database diagnostics or
runtime secrets into chat. `backup-status` is completion history, not a new
repository-integrity check.

## Controlled installation and updates

There is no sudo installation action, arbitrary file argument, shell action, or
permission to execute a script under the application directory. The Python
wrapper uses isolated mode, fixed executable paths, a clean child environment,
and root-owned checksum-checked scripts in `/usr/local/lib/reachsocial-ops`.
The installer checks the bundle's SHA-256 and embedded full git commit, permits
only five named regular files, validates syntax/sudoers, and installs code before
enabling the exact sudo commands and replacing the existing nightly cron entry.
It refuses writable/untrusted parent directories and a missing production mount.

On Herald, after committing and reviewing the package:

```bash
mkdir -p data/operations-install
git rev-parse HEAD
git archive --format=tar HEAD deploy/operations/reachsocial-ops.py \
  deploy/operations/sudoers deploy/operations/cron \
  scripts/backup_droplet.sh scripts/verify_nightly_restore.sh \
  > data/operations-install/operations.tar
git show HEAD:scripts/install_operations.py > data/operations-install/install_operations.py
sha256sum data/operations-install/operations.tar data/operations-install/install_operations.py
```

Review the commit and both hashes on Herald. Stage these two files under
`/mnt/reachsocial_data_tor1_01/apps/reachsocial/operations-install/` using the
deployment SSH account. A staged checksum file is not approval: the owner must
use the independently reviewed literal hashes in the console command.

In the **Droplet root Recovery Console**, use the prepared command to read the
installer bytes with `/usr/bin/python3 -I`, check their reviewed literal SHA-256,
and execute those same verified bytes in memory. It supplies three installer
arguments: the staged bundle path, approved full commit, and approved bundle
SHA-256. The installer also hashes the same bundle bytes it parses, avoiding
staging races. Do not execute a staged path directly after checking its hash,
use `curl | bash`, or grant the installer sudo.

Install outside the old nightly job's runtime; the old job does not share the
new lock. Keep the console open for acceptance:

```bash
visudo -c
sshd -T | grep '^permitrootlogin no$'
runuser -u reachsocial -- sudo -n /usr/local/sbin/reachsocial-ops backup
runuser -u reachsocial -- sudo -n /usr/local/sbin/reachsocial-ops verify-restore
runuser -u reachsocial -- sudo -n /usr/local/sbin/reachsocial-ops backup-status
# These must be refused:
runuser -u reachsocial -- sudo -n /usr/local/sbin/reachsocial-ops backup extra
runuser -u reachsocial -- sudo -n /usr/bin/true
```

From a second Herald SSH connection, repeat status and health checks. Record
the approved commit and successful backup/restore timestamps before closing
the console. Future routine runs need no console; changing privileged scripts
requires another reviewed commit/checksum installation by the owner.

The installer keeps previous files under `previous-install` in its root-only
state directory. Before another update, archive that directory under a dated
name using the console. If initial acceptance fails, disable the new sudoers
entry and restore the saved `reachsocial-backup` cron file (mode 0644). For an
update rollback, restore saved scripts/manifest/wrapper and sudoers to their
original paths and modes, then run `visudo -c`. Do not restore a backup into
production as part of wrapper rollback.

## Exceptional recovery

The owner saves the Droplet root password in their password manager, associated
with Droplet ID/IP and the DigitalOcean account. Do not put it in this checkout,
GitHub secrets, shell history, or chat. Password-manager storage and a successful
console login must be confirmed by the owner; this automation cannot attest to them.

Use DigitalOcean's **Settings → Recovery console → Launch Console** and log in
as root. This out-of-band console works independently of SSH. If no root password
is available, the owner can use **Reset root password**, then change the temporary
password on console login and save the replacement. Keep `PermitRootLogin no`;
console password login does not require enabling root SSH. See the
[DigitalOcean recovery procedure](https://docs.digitalocean.com/products/droplets/how-to/recovery/recovery-console/).

Confirm the volume is mounted with `mountpoint /mnt/reachsocial_data_tor1_01`
before starting Docker/containerd or running backups. Check `sshd -t`, effective
`sshd -T` configuration, the deployment account's authorized key, and service
health as applicable. Make only the needed repair; validate a new deployment
SSH session and public `/healthz` before leaving the console. A volume loss or
production database replacement is a separate owner-approved disaster-recovery
operation, not the `verify-restore` action.

## Evidence and remaining acceptance

- 2026-10-15: existing deployment SSH works; `/healthz` returns `ok`; running
  ReachSocial image is `7bd3b59e1087a5c81afd9ef6345dd8608ad9d970`.
- Owner console installation of `575ba99dba6e66d44169e52502535f89366bd6f5`
  succeeded. A separate deployment SSH session confirmed all three exact sudo
  commands; extra arguments and `/usr/bin/true` are denied. The wrapper is
  `root:root 0755`, its code directory is `root:root 0700`, and the existing
  08:17 UTC cron now invokes the wrapper. `reachsocial` retains Docker membership.
- Fresh encrypted backup passed at `2026-10-15T18:34:46.734635+00:00` (exit 0).
  The first restore attempt failed at `18:35:57.233604+00:00` during isolated
  app startup. Reproduction with an empty database identified the verifier's
  `http://restore.local` issuer: the OAuth library requires HTTPS except on
  loopback addresses. The correction uses `http://127.0.0.1:8000`.
- The corrected issuer passed health, both OAuth discovery endpoints, and the
  MCP 401 challenge in the exact production image with an empty temporary
  database, no network, and payments disabled. The temporary container was
  removed. This startup probe does not replace a successful encrypted restore.
- Root SSH rejected the deployment key (`Permission denied (publickey)`). The
  readable `60-reachsocial-security.conf` specifies `PermitRootLogin no`; a full
  privileged `sshd -T` check was not performed. Production health remains `ok`.
- Corrected backup/restore scripts committed as `72f1512`; shell syntax,
  ShellCheck, sudoers syntax, and Ruff pass. The full Python suite reports 233
  passed and 17 credential-gated tests skipped; TypeScript typechecking and 36
  frontend tests pass. Sixteen operations tests cover command restrictions,
  environment, checksums, archive validation, locking, failure status, mount/root
  checks, installer validation, distinct rollback copies of sudoers/wrapper,
  and the restore issuer's compatibility with the OAuth library.
- Historical isolated SQLite restore evidence remains in
  [self-service release](self-service-release.md#isolated-restore-and-transport-verification).
- **Pending:** owner installation of the corrected verifier and a successful
  encrypted restore run, plus owner confirmation of password-manager storage.
  The owner supplied successful root-console installation output; exceptional
  network/volume failure recovery was not simulated. Do not mark the nightly
  restore complete until the corrected script passes through the wrapper.
