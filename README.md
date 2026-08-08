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

Create the first internal B2B client only after the service starts:

```bash
uv run python scripts/create_client.py InstaGet --billing-mode internal
```

The script prints the private key once. Put it in the protected InstaGet server
environment during that separate integration release; never send it to a browser
or commit it.

## Production gates

`deploy/.env.production.example` documents the protected host environment.
Provision a dedicated `tor1` Droplet, firewall, persistent volume, and DNS first.
The deployment workflow expects separate `REACHSOCIAL_*` GitHub secrets.
Docker Compose reads the Caddy bcrypt hash from the protected `.env` file. Put
that value in single quotes (as in the production template) so its `$` characters
remain literal; the quotes are not part of the hash.
Set `REACHSOCIAL_ADDRESS` to the production hostname for normal HTTPS. During
an IP-only deployment, set it to `http://<public-ip>` until DNS is connected.

Provider services remain disabled until their route, credentials, price, and
contract tests are configured. MCP is B2B-only when enabled. x402 uses the CDP
facilitator with short-lived server-side JWTs when enabled; B2B Bearer-key calls
remain payment-free. Keep `X402_ENABLED=false` until a Base Sepolia payment test
succeeds, then switch the network to `eip155:8453` only when the receiving wallet
is intended to accept mainnet USDC.

Schedule `uv run python scripts/prune_retention.py` daily on the production host
and `scripts/backup_sqlite.sh` after installing `sqlite3` and configuring its
protected encryption key and backup destination.
