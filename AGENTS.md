# Agent instructions

Read this file before changing ReachSocial. Keep operational facts here and
link to detailed product evidence instead of copying it.

## Project boundary

- ReachSocial owns the social-data API, public catalog and website, normalized
  provider contracts, authenticated B2B access, MCP, and public REST x402.
- It is separate from InstaGet and Agent Enhancer Utilities (AEU): do not share
  application databases, runtime secrets, migrations, or deployment files.
- ReachSocial owns the shared Caddy ingress for `reachsocial.dev` and
  `liberated.site`. AEU joins the external `reachsocial_edge` Docker network
  and does not bind host ports 80 or 443.
- Start with `README.md`. Read `docs/readiness.md` for release gates,
  `docs/provider-contract-status.md` for provider evidence, and
  `docs/roadmap.md` before any mainnet-payment work.

## Herald workspace

- The convenient path `/home/herald/Desktop/reachsocial` is a symlink. The
  working tree lives at `/mnt/instaget-nvme/herald-work/reachsocial`.
- AEU is the sibling worktree at
  `/mnt/instaget-nvme/herald-work/agent-enhancer-utilities`.
- Local Docker data lives at `/mnt/instaget-nvme/docker/docker`; containerd
  state lives at `/mnt/instaget-nvme/docker/containerd`. The NVMe must be
  mounted before either service starts. Do not put builds, images, or backups
  back on Herald's root filesystem.
- Preserve unrelated local InstaGet containers when testing or cleaning Docker.

## Development and verification

Use Python 3.12 and the locked `uv` environment:

```bash
uv sync --all-groups --frozen
uv run ruff check .
uv run pytest
```

Live provider tests are skipped by default. Run paid or credentialed provider
commands only when the task explicitly calls for them and keep their existing
cost caps and confirmation flags.

The local app starts with:

```bash
uv run alembic upgrade head
uv run uvicorn reachsocial.main:app --reload
```

The health endpoint is `/healthz`. Public discovery starts at `/agent.md`,
`/llms.txt`, `/openapi.json`, and `/.well-known/api-catalog`.

## Production and deployment

- The canonical production branch is `main`. A push to `main` runs
  `.github/workflows/deploy.yml`, builds an immutable image tagged with the full
  commit SHA, snapshots the SQLite database, deploys it, verifies health, and
  reprovisions the scoped `InstaGet-Herald` client.
- The local `host-migration` branch may mirror `main`; do not treat it as a
  separate product line.
- Production files live on the attached DigitalOcean volume under
  `/mnt/reachsocial_data_tor1_01/apps/reachsocial`. Docker and containerd data
  on the Droplet also live under that volume. Root-disk paths are not the
  deployment source of truth.
- Verify a release at `https://reachsocial.dev/healthz`, then confirm the
  running image tag contains the exact deployed SHA.

## Secrets, state, and backups

- `.env` is runtime configuration and must never be printed or committed.
  GitHub deployment credentials stay in GitHub secrets and variables.
- ReachSocial production state is SQLite in the named Docker volume. AEU uses
  PostgreSQL; never point one application at the other's database.
- `scripts/backup_droplet.sh` creates consistent ReachSocial SQLite and AEU
  PostgreSQL backups on the DigitalOcean volume. The host runs it nightly.
- `.github/workflows/volume-backup.yml` creates the off-host DigitalOcean volume
  snapshot and retains the four newest automated snapshots.
- This installation intentionally does not use AWS or S3. Do not reintroduce
  AWS environment keys or an S3 Restic repository without a new decision.

## Payments and provider safety

- Normal public x402 currently uses Base Sepolia. A five-cent Base-mainnet
  canary and the separate three-route independent acceptance both settled on
  2026-10-11, but the acceptance handler is now disarmed and neither result
  authorizes general public sales.
- Do not set `X402_NETWORK=eip155:8453` or `ALLOW_MAINNET_X402=true` until every
  item in `docs/roadmap.md` is complete. The CDP credential identified there
  must be rotated before mainnet use.
- The public Instagram routes use the documented 1,880 micro-USD
  replacement-cost basis plus observed one-credit endpoint use. It is not an
  invoice. Recheck the balance before mainnet, set
  `SCRAPECREATORS_CREDIT_BALANCE` and the protected
  `SCRAPECREATORS_CREDIT_RESERVE`, and retain the $5 daily upstream cap. No
  code path may top up credits automatically.
- Anonymous paid calls require `Idempotency-Key`. Same-key/same-input retries
  recover the stored result; `POST /v1/payments/recover/{service}` is the
  explicit recovery route. Do not retain payment signatures or recovery
  phrases.
- `PUBLIC_PAYMENTS_PAUSED=true` blocks new x402 challenges but preserves paid
  result retrieval and accepted jobs. Facilitator uncertainty is
  `reconciliation_required`, never an automatic retry or assumed cancellation.
  See `docs/public-payment-operations.md`.
- Never log raw provider payloads, provider credentials, wallet secrets, B2B
  API keys, or unredacted environment files.
