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
npm ci
npm run typecheck
npm test
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

Browser onboarding lives in `examples/browser/reachsocial-client.ts` and
`quickstart.ts`; the docs render those tested sources directly. Keep the
wallet-readiness panel read-only, preserve request keys before payment, and
never replace recovery with a new paid execution. See
`docs/onboarding-audit-2026-10-14.md` for its checks and outstanding live gate.

## Production and deployment

- `artiehinz/reachsocial` is the private application/deployment repository.
  `artiehinz/ReachSocial.dev` is a separate client-documentation repository;
  never push this application tree or its history there. Its independent checkout
  is `/mnt/instaget-nvme/herald-work/reachsocial-public-docs.xDAt7C`.
  It is currently private pending cleanup of GitHub's retained historical
  objects. See `docs/public-repository-cleanup.md` before changing visibility.

- The canonical production branch is `main`. A successful CI run for a `main`
  commit runs `.github/workflows/deploy.yml`, builds an immutable image tagged
  with that exact commit SHA, snapshots the SQLite database, synchronizes and
  validates Compose and Caddy configuration, deploys it, verifies health, and
  reprovisions the scoped `InstaGet-Herald` client.
- The local `host-migration` branch may mirror `main`; do not treat it as a
  separate product line.
- Production files live on the attached DigitalOcean volume under
  `/mnt/reachsocial_data_tor1_01/apps/reachsocial`. Docker and containerd data
  on the Droplet also live under that volume. Root-disk paths are not the
  deployment source of truth.
- Both domains are proxied by Cloudflare with authenticated origin pulls
  enabled. Caddy requires Cloudflare's client certificate, and the host's
  Docker `DOCKER-USER` chain permits only current Cloudflare ranges on inbound
  TCP and UDP 443. Keep `deploy/firewall/reachsocial-origin-firewall.sh`
  aligned with Cloudflare's published IP ranges; port 80 remains public for
  certificate renewal and only redirects to HTTPS.
- GitHub deployments authenticate as the non-root `reachsocial` account. Root
  SSH login is disabled; use the provider console for break-glass recovery.
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

- Normal public x402 uses Base mainnet for services marked available in the
  reviewed catalog. The canary and independent acceptance handlers are
  disarmed. See `docs/readiness.md` for the current executable set; private
  services still require their individual provider, paid-recovery, and
  observation gates in `docs/roadmap.md` before promotion.
- The CDP credential was rotated before the two-service mainnet release. Do
  not expose another public service merely because its adapter works.
- The public Instagram routes use the documented 1,880 micro-USD
  replacement-cost basis plus observed one-credit endpoint use. It is not an
  invoice. Recheck the balance before mainnet, set
  `SCRAPECREATORS_CREDIT_BALANCE` and the protected
  `SCRAPECREATORS_CREDIT_RESERVE`, and retain the $5 daily upstream cap. No
  code path may top up credits automatically.
- Every public-mainnet ScrapeCreators settlement must pass the live,
  account-wide balance check before funds settle. Subtract the 1,000-credit
  internal reserve plus active public holds; fail closed when the check is
  unavailable.
- Anonymous paid calls require `Idempotency-Key`. Same-key/same-input retries
  recover the stored result; `POST /v1/payments/recover/{service}` is the
  explicit recovery route. Do not retain payment signatures or recovery
  phrases.
- `PUBLIC_PAYMENTS_PAUSED=true` blocks new x402 challenges but preserves paid
  result retrieval and accepted jobs. Facilitator uncertainty is
  `reconciliation_required`, never an automatic retry or assumed cancellation.
  See `docs/public-payment-operations.md`.
- New anonymous paid calls require a random 32–255 character idempotency key.
  System-wide operational alerts latch all new payments off and make `/readyz`
  return 503. Repeated retryable failures in one provider route open only that
  public service's circuit before payment; `/readyz` remains 200 with a degraded
  service list. Recovery and accepted jobs remain available in both cases.
- Never log raw provider payloads, provider credentials, wallet secrets, B2B
  API keys, or unredacted environment files.
