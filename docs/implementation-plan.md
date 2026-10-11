# Archived ReachSocial implementation plan

This pre-release design note is retained only for historical context. It
predates the ScrapeCreators-only social catalog and describes retired Apify
options; use [the roadmap](roadmap.md), [readiness notes](readiness.md), and
[provider contract status](provider-contract-status.md) for current work.

## Product boundary

ReachSocial is a standalone social-data service and B2B/API product. InstaGet is
its first B2B client, but ReachSocial must not share InstaGet's application,
database, runtime, deployment target, or credential namespace.

ReachSocial stores only client, request, usage, cache, provider-cost, payment,
and operational records. It does not download, compress, or persist requested
media. InstaGet retains ownership of users, people data, libraries, and
notification state.

The first production release is internal: InstaGet calls ReachSocial through a
private B2B API key. Public REST, MCP, and x402 are enabled only after that path
is stable.

## Locked MVP decisions

| Area | Decision |
| --- | --- |
| Application | One Python/FastAPI service for API, website, OpenAPI, MCP, and x402. |
| Hosting | A separate small DigitalOcean Droplet in `tor1`, using Docker Compose and Caddy. |
| Network | Same VPC/region as InstaGet where supported; public API remains TLS-only. |
| Environments | Local development and a separate ReachSocial production deployment. No ReachSocial Herald deployment. |
| Database | SQLite on a persistent Droplet volume for MVP; migrate to managed PostgreSQL later. |
| Cache and limits | Process-memory only for MVP. It is expendable and never used for durable accounting. |
| Authentication | API keys for B2B clients, stored only as hashes. InstaGet is the first client. |
| Providers | ScrapeCreators first; selected Apify actors only for coverage gaps. |
| Public charging | Fixed per-endpoint x402 payments. Prepaid credit bundles are post-MVP. |
| Storage | Request metadata and short-lived JSON response cache only; no media/object storage. |

## Architecture

```text
InstaGet server                         Public REST / MCP / x402 client
       |                                              |
       +----------- ReachSocial API -----------------+
                              |
                    auth, limits, pricing
                              |
                       service router
                              |
              ScrapeCreators / selected Apify actors
                              |
            stable envelope + usage/cost records
```

The InstaGet browser never receives a ReachSocial key. InstaGet's backend
normalizes a user-provided social URL, calls ReachSocial, and returns the result
for rendering. Its later simplified search flow must not store the media,
archive it, or add it to the personal library.

## Service contract

Public paths never disclose a provider. Each service has a provider-neutral
identifier such as `instagram.post`, `x.post`, `tiktok.video`, or
`linkedin.profile`.

Every enabled service configuration contains:

- service ID, platform, input schema, output notes, and public enabled state;
- provider adapter and route;
- synchronous timeout, retry policy, and cache TTL;
- estimated upstream cost and fixed selling price; and
- public documentation, MCP description, and x402 price metadata.

The initial response envelope is:

```json
{
  "request_id": "req_...",
  "service": "instagram.post",
  "status": "success",
  "cached": false,
  "data": {},
  "meta": {
    "schema_version": "1.0",
    "normalization_version": "v1",
    "response_shape": "profile|item|feed|stories",
    "latency_ms": 0
  }
}
```

Provider payloads never enter the consumer envelope. ReachSocial normalizes
input validation, request IDs, status/error codes, and only the small common
fields needed by its clients. InstaGet validates the versioned envelope before
persistence and never exposes provider/raw fields to its browser. Long Apify
work uses durable asynchronous jobs with protected polling and replacement
credits for eligible paid failures.

## Records and controls

SQLite must durably record:

- `clients`: name, API key hash, status, limits, and billing mode;
- `services`: routing, price, upstream-cost estimate, availability, timeout,
  and cache policy;
- `requests`: request ID, client, service, provider, timing, cache result,
  upstream cost, charge, and structured error code; and
- `payments`/`receipts`: x402 transaction verification and replay-protection
  state.

In-memory cache entries contain response JSON only and expire quickly (default
60 seconds unless a service requires another TTL). Cache contents are never a
source of accounting truth. The MVP applies per-client request concurrency and
rate limits, plus provider-level hard concurrency/cost caps. Failed upstream
requests never charge a client.

Every Apify Actor start supplies a validated dataset-item bound, a positive
maximum total charge, and an Actor timeout. ReachSocial persists the accepted
run ID before polling, resumes that same run after worker recovery, and never
automatically creates a replacement paid run.

## Initial catalog

Build the configuration and website structure for Instagram, TikTok, YouTube,
X, Facebook, Reddit, and public LinkedIn data. Only services that have a tested
provider route, fixed price, and operational limit are marked enabled.

The initial internal migration inventory in InstaGet is:

- Instagram profiles, posts, and stories via Apify;
- X/Twitter profiles and posts via Apify;
- TikTok profiles and videos via Apify; and
- LinkedIn profiles via an Apify actor.

No current ScrapeCreators integration was found in InstaGet. No direct NewsAPI
provider client was identified in the initial provider scan; treat any news
workflow as a later discovery item rather than silently migrating it.

## Website and documentation

The server-rendered website includes home, platform catalog, service details,
pricing, API documentation, MCP/x402 onboarding, status, and contact pages.
Generate its catalog, prices, endpoint details, OpenAPI annotations, MCP tool
descriptions, and `llms.txt` from the service configuration.

Use StableSocial as a page-structure and information-architecture reference,
not a source of copied wording or branding. Reuse Liberated components only
when their source is owned or licensed for reuse; ReachSocial has no runtime or
code dependency on either site.

## Deployment

1. Provision a new, dedicated Droplet, firewall, VPC attachment, DNS target,
   SSH deploy identity, and persistent application volume. Do not alter any
   InstaGet resource.
2. Deploy Docker Compose with the FastAPI application and Caddy. Caddy obtains
   and renews TLS for `reachsocial.dev`.
3. Use a separate GitHub Actions workflow and ReachSocial-prefixed secrets.
   Existing credential values may be duplicated only with approval; existing
   InstaGet secrets are never read, changed, rotated, or deleted.
4. Build an immutable image, deploy it to the ReachSocial host, run migrations,
   health-check it, and retain the prior image for rollback.
5. Back up the SQLite database before public payment launch.

DNS can be managed through Namecheap once its MCP connection is authorized.
Credentials must be installed through the connector or repository/deployment
secret mechanism, never committed or pasted into source files.

## Delivery sequence and release gates

### Phase 1: foundation

- Scaffold FastAPI, Docker, Caddy, local configuration, health/readiness
  routes, SQLite migrations, test tooling, and CI.
- Add production Droplet provisioning and a separate deployment workflow.
- Confirm `reachsocial.dev` DNS, TLS, health check, logs, and rollback.

### Phase 2: internal core

- Implement the service catalog, adapter interface, API-key authentication,
  request envelope, idempotency key handling, request records, cost records,
  short cache, limits, and owner-only operations page.
- Seed InstaGet as a client. Generate its key once and store only its hash in
  ReachSocial.
- Implement the ScrapeCreators adapter after credentials and endpoint details
  are supplied. Add only required Apify fallback adapters.

### Phase 3: InstaGet integration

- Add a server-to-server ReachSocial client to InstaGet behind a per-service
  migration/rollback flag.
- Start with URL normalization and the profile/post/video result flow.
- Remove the old local-media and people-page social overview behavior only in
  the separately planned InstaGet simplification release.
- Require end-to-end testing for invalid URLs, profiles, posts, pagination,
  upstream timeouts, duplicate/retry behavior, results rendering, latency, and
  provider-cost caps.

### Phase 4: public surface

- Publish REST, generated OpenAPI, enabled-service docs, and MCP tools.
- Add x402 verification, Base USDC receiving-wallet configuration, payment
  receipts, replay protection, and real low-value wallet tests.
- Enable x402 only for short, reliable, synchronous services with verified
  price margin.

### Phase 5: launch

- Verify normal InstaGet production workloads remain stable on ReachSocial.
- Add minimum Terms, Privacy, acceptable-use, refunds, and request-retention
  language before any public paid endpoint is enabled.
- Publish the service catalog and begin registry/directory submissions only
  after production payment and reliability gates pass.

## Required inputs before provider/payment work

- ScrapeCreators API credential and current endpoint documentation;
- any approved Apify tokens and actor IDs;
- Base USDC receiving-wallet/payment-verification configuration; and
- Namecheap MCP authorization for DNS changes.

These inputs are not needed to begin the foundation, catalog, auth, website,
deployment, and test scaffolding.
