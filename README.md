# ReachSocial

ReachSocial is a provider-neutral social-data service for InstaGet, B2B clients,
and agentic clients. It is intentionally separate from InstaGet's application,
database, runtime, and deployment target.

## Local development

```bash
cp .env.example .env
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn reachsocial.main:app --reload
```

Open `http://localhost:8000`, `http://localhost:8000/docs`, and
`http://localhost:8000/openapi.json`.

Machine clients can start at `/llms.txt`, `/agent.md`,
`/.well-known/api-catalog`, or the typed `/openapi.json`. The executable
catalog at `/v1/services` contains only services that can be called now;
`/v1/catalog` also includes private, validation, planned, and paused services. A catalog
entry is never an implicit promise that its route is executable.

Create B2B clients only after the service starts. Passing one or more
`--service` flags creates a restricted entitlement set; omitting them preserves
legacy access to every public service:

```bash
uv run python scripts/create_client.py ExampleClient --billing-mode metered \
  --service instagram.profile --service instagram.post
```

The script prints an indexed `rs_live_<key_id>_<secret>` key once. Never send it
to a browser or commit it. Existing legacy ReachSocial keys remain valid until
rotation. Rotate, revoke, change entitlements or limits, and inspect usage with:

```bash
uv run python scripts/manage_clients.py rotate ExampleClient
uv run python scripts/manage_clients.py revoke ExampleClient
uv run python scripts/manage_clients.py entitle ExampleClient x.profile
uv run python scripts/manage_clients.py limits ExampleClient --daily-spend-cents 1000
uv run python scripts/manage_clients.py usage ExampleClient
```

The production workflow idempotently provisions the approved `InstaGet-Herald`
client from its protected key and explicit internal service allowlist.

## API contract

Synchronous services use `POST /v1/services/{service_id}/execute`. Long-running
services use `POST /v1/services/{service_id}/jobs`, followed by
`GET /v1/jobs/{job_id}`. Anonymous jobs require the returned `X-Job-Token`;
only its scrypt hash is stored. Eligible paid job failures can claim one
same-service, one-use replacement credit at `POST /v1/jobs/{job_id}/credit`.

All successful responses use normalized schema `1.0`. ReachSocial stores source
URLs and normalized metadata only; it never downloads social-media bytes and
never returns raw provider payloads or provider names.

Run a single sanitized provider/cost sample only with explicit acknowledgement:

```bash
uv run python scripts/provider_contract_smoke.py x.profile https://x.com/example \
  --credit-cost-microusd 1880 --confirm-paid-provider-call
```

For ScrapeCreators, calculate `--credit-cost-microusd` from the plan actually
purchased. The script reports units, micro-USD cost, margin, normalized shape,
and provider reference without printing credentials or raw provider data.

Convert the actual pack price and credit count into conservative catalog values
without making a provider request:

```bash
uv run python scripts/calculate_scrapecreators_cost.py \
  --pack-price-usd 19 --credits 10000
```

The command does not edit the catalog or mark a cost verified. Save the plan or
invoice reference and verification date before applying its result.

Run a bounded release-contract stage only with an explicit confirmation. The
local mode-0600 ledger records hashes and accounting only; it never stores a
source URL, provider payload, credential, payment signature, or wallet material.

```bash
uv run python scripts/release_provider_acceptance.py --help
```

The current reviewed catalog has 18 entries across eight platforms: two
available on Base mainnet, fifteen private integrations, and one paused
service. A 2026-10-11 bounded run verified 13 ScrapeCreators contracts at one
credit each. `linkedin.profile` is a private integration while its replacement
endpoint still returns `not_found` for the supplied target and the provider's
documented sample; it is not cleared for public payment. `news.person` remains
private after its initial GDELT rate limit cleared on a bounded retry. Instagram
current stories remains paused because there is no accepted ScrapeCreators
contract.

The private `news.person` service gives the scoped InstaGet Herald client a
sanitized, cached GDELT news boundary without exposing it as a paid public API.
The generated
ScrapeCreators review inventory is intentionally broader—currently 178
operations—but those routes are not public pass-throughs. See
`docs/catalog-expansion.md` for the admission rules and batching order.
The current cross-product gate matrix is in `docs/readiness.md`.

## Production gates

`deploy/.env.production.example` documents the protected host environment.
Provision a dedicated `tor1` Droplet, firewall, persistent volume, and DNS first.
The deployment workflow expects separate `REACHSOCIAL_*` GitHub secrets.
Docker Compose reads the Caddy bcrypt hash from the protected `.env` file. Put
that value in single quotes (as in the production template) so its `$` characters
remain literal; the quotes are not part of the hash.
Set `REACHSOCIAL_ADDRESS` to the production hostname for normal HTTPS. During
an IP-only deployment, set it to `http://<public-ip>` until DNS is connected.

Production MCP is enabled as an authenticated B2B surface; public REST uses the
CDP x402 facilitator on Base mainnet (`eip155:8453`) for Instagram profile and
post. B2B Bearer-key calls bypass x402. The public payment path enforces a $5 UTC-day paid-provider cost cap, per-IP
and per-payer limits, and shared concurrency bounds. Provider costs are recorded
in integer micro-USD.

When the dedicated buyer account has testnet USDC and its three CDP secrets are
available only in the protected shell environment, the guarded payment smoke
command validates the exact network, receiver, and five-cent maximum before
signing, then sends exactly one paid retry:

```bash
uv run python scripts/x402_sepolia_smoke.py \
  --profile-url https://www.instagram.com/instagram/ \
  --expected-pay-to <production-receiving-address> \
  --confirm-testnet-payment
```

It prints a sanitized settlement summary and transaction reference. It does
not read a repository `.env`, print a secret, perform automatic payment
recovery, or make a second paid attempt.

For the later Base-mainnet canary, create the buyer wallet locally before it is
funded. This command has no network access and writes no wallet material to
disk; it displays a recovery phrase once, which must be saved in the owner's
password manager. Never run it on the Droplet, in CI, or through a remote shell.

```bash
uv run python scripts/create_mainnet_buyer_wallet.py create \
  --confirm-create-mainnet-buyer-wallet
uv run python scripts/create_mainnet_buyer_wallet.py verify \
  --expected-address <address-printed-by-create>
```

After the verification succeeds, fund that Base address only with the exact
USDC canary amount and the minimum Base ETH required for its transaction fee.

### One-time Base-mainnet canary

The mainnet canary is a separate hidden route, not a public launch. It stays
off by default. When it is armed in the protected production environment, it
accepts exactly one five-cent native-USDC payment from the named buyer address,
for `instagram.profile`; the database permanently rejects a second verified
payment. Keep `X402_NETWORK=eip155:84532` and leave `ALLOW_MAINNET_X402=false`.

```ini
MAINNET_X402_CANARY_ENABLED=true
MAINNET_X402_CANARY_BUYER=<verified-buyer-address>
```

The buyer runs the following locally after the production deployment is healthy.
It reads the recovery phrase through hidden terminal input and makes one paid
retry only after validating the Base-mainnet network, native-USDC asset,
receiver, and five-cent amount.

```bash
uv run python scripts/x402_mainnet_canary.py \
  --profile-url https://www.instagram.com/instagram/ \
  --expected-buyer <verified-buyer-address> \
  --expected-pay-to <production-receiving-address> \
  --confirm-mainnet-canary
```

Base mainnet is active for Person News, Instagram profile and post, and the X
and TikTok profile, post, and feed services. Startup still blocks `eip155:8453`
unless every public service has verified margins,
`ALLOW_MAINNET_X402=true`, and encrypted external recovery is enabled. Nightly
encrypted Restic backups and weekly DigitalOcean volume snapshots are configured.
Private services remain outside public payment until each completes its own
provider, paid-recovery, and observation gates.

The application runs retention maintenance daily. Deployments take a bounded
same-volume SQLite snapshot before migration, wait for `/readyz`, automatically
restore the previous image on failure, and retain the active plus immediately
previous images. Same-volume snapshots do not satisfy the external-backup gate.

InstaGet consumes the private Instagram, X, TikTok, and YouTube services through
its separate server-only client; ReachSocial still never downloads media bytes.
