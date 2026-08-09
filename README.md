# ReachSocial

ReachSocial is a provider-neutral social-data service for InstaGet, B2B clients,
and agentic clients. It is intentionally separate from InstaGet's application,
database, runtime, and deployment target.

## Local development

```bash
cp .env.example .env
uv sync --all-groups
uv run uvicorn reachsocial.main:app --reload
```

Open `http://localhost:8000`, `http://localhost:8000/docs`, and
`http://localhost:8000/openapi.json`.

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

Do not create the InstaGet client yet. That key is created only in the separately
approved Herald integration cycle so its raw value can go directly into protected
InstaGet server environments.

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

The Apify-backed Instagram Stories, X latest-feed, and LinkedIn enrichment
adapters and job contracts are implemented but remain catalog-disabled until
Apify billing/actor access is healthy and credentialed runs establish their
actual costs. Do not enable them based on estimates alone.

## Production gates

`deploy/.env.production.example` documents the protected host environment.
Provision a dedicated `tor1` Droplet, firewall, persistent volume, and DNS first.
The deployment workflow expects separate `REACHSOCIAL_*` GitHub secrets.
Docker Compose reads the Caddy bcrypt hash from the protected `.env` file. Put
that value in single quotes (as in the production template) so its `$` characters
remain literal; the quotes are not part of the hash.
Set `REACHSOCIAL_ADDRESS` to the production hostname for normal HTTPS. During
an IP-only deployment, set it to `http://<public-ip>` until DNS is connected.

MCP remains disabled in this cycle. Public REST uses the CDP x402 facilitator on
Base Sepolia (`eip155:84532`); B2B Bearer-key calls bypass x402. The public test
path enforces a $5 UTC-day paid-provider cost cap, per-IP and per-payer limits,
and shared concurrency bounds. Provider costs are recorded in integer micro-USD.

Do not switch to Base mainnet. Startup blocks `eip155:8453` unless every public
service has verified positive margins, `ALLOW_MAINNET_X402=true`, and an encrypted
external backup is enabled. Mainnet also remains operationally blocked until a
restore drill, legal/TLS/replay/alert checks, and the planned Droplet resize pass.

The application runs retention maintenance daily. Deployments take a bounded
same-volume SQLite snapshot before migration, wait for `/readyz`, automatically
restore the previous image on failure, and retain the active plus immediately
previous images. Same-volume snapshots do not satisfy the external-backup gate.

InstaGet code, data, provider calls, media storage, people pages, library, and
deployment are intentionally outside this cycle and remain unchanged.
