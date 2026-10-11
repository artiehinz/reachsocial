# Prelaunch audit — 2026-10-11

## Decision

Keep general Base-mainnet sales disabled until the owner makes the final release
decision. Earlier acceptance and refund evidence remains valid. The four holds
found by this audit were resolved on 2026-10-11 without a new paid provider
request or transfer.

## Implemented API coverage

The runtime catalog has 17 services: 3 public, 11 private, 2 planned, 1 paused.
Twelve enabled adapters use ScrapeCreators:

| Platform | Public | Private / explicitly entitled B2B |
| --- | --- | --- |
| Instagram | profile, post | feed |
| X | — | profile, post, feed (public posts, not guaranteed latest) |
| TikTok | — | profile, video, feed |
| YouTube | — | channel, video, feed |

LinkedIn profile is the third public route and uses Apify. Private news.person
uses GDELT. Facebook profile and Reddit post are planned; Instagram stories
is paused. The broader generated endpoint inventory is not an implemented API
catalog. This audit adds no new wrappers and does not run fresh live coverage.

## Resolved launch holds

1. **Shared credit budget — resolved.** Every new public-mainnet Instagram
   settlement now reads the account-wide ScrapeCreators balance before funds
   settle. The live value already includes InstaGet and other private usage;
   ReachSocial subtracts the 1,000-credit internal reserve and active public
   reservations. An unavailable or invalid balance aborts before settlement.
   Completed historical reservations are reconciled at startup and are not
   subtracted again from a fresh provider balance.
2. **Agent access at Cloudflare — resolved.** A zone custom rule skips Browser
   Integrity Check only for ReachSocial API, MCP, health, and machine-readable
   discovery paths. Python urllib, curl, and the browser can reach those paths;
   Browser Integrity Check remains enabled for ordinary website pages.
3. **Recovery key strength — resolved.** New anonymous paid calls are rejected
   before their payment challenge unless the idempotency key is 32–255
   characters. Existing paid records remain recoverable with their original
   key and matching input. Bundled buyer scripts now generate 128 random bits.
4. **Monitoring — resolved.** Critical application alerts latch an in-process
   pause for new payment challenges and make `/readyz` return 503. Paid recovery
   and accepted background jobs remain available. A three-region DigitalOcean
   uptime check watches `/readyz`; global failure and TLS-expiry policies notify
   the verified DigitalOcean account email. Resume after investigation by
   recreating the app with healthy conditions and the existing image.

## Security review scope and observations

Reviewed auth, payment hooks, recovery, credit reservations, URL normalization,
logging, process-local limits/cache, container/ingress configuration, and retention.
Scrypt API-key hashing, constant-time admin-token comparison, explicit client
entitlements, protected job polling, durable payment replay records, and uncertain
settlement state are implemented. Payment and operational responses default to
no-store. The app runs as a non-root container user; port 8000 is not published
on the host. Caddy normalizes forwarded client addresses.

This is not a penetration test or dependency vulnerability audit. Unauthenticated
CPU/body abuse, multi-process races, host firewall configuration, and all external
provider failure modes are not certified by this review. Process-local rate,
concurrency, and in-flight spend state assumes the current single-process runtime;
do not add workers/replicas without shared enforcement. Runtime cache and lock
maps are not globally bounded; expire/evict unused entries before sustained load.
The ingress container now receives only its address and Basic Auth settings,
rather than the application provider and payment credentials. The deployment
workflow synchronizes and validates Compose and Caddy configuration before
starting the immutable image, so host configuration cannot silently lag source.

Added nosniff, referrer policy, frame denial, and a restrictive CSP for the public
HTML pages. Swagger/ReDoc keep their interactive scripts. No claim of complete
security follows from adding headers or passing the unit suite.

## Caching

Observed through Cloudflare using GET requests:

- CSS: HIT, edge age present; browser max-age 14,400 seconds (edge override),
  shared-cache max-age 86,400 seconds. Versioned the stylesheet URL for releases.
- Homepage: DYNAMIC, origin Cache-Control public, browser 60 seconds,
  shared-cache 120 seconds, stale-while-revalidate 300 seconds. Headers alone
  do not establish that Cloudflare caches HTML.
- Discovery: code permits browser 60 seconds / shared-cache 300 seconds.
- Paid POST, job/recovery, owner and health responses: no-store by default.
- Provider-result cache: process-local; profiles 6 hours, individual posts/videos
  1 hour, feeds 10 minutes. These are distinct from website caching and paid
  result recovery. Cache contents disappear on restart.

## Website corrections

Made testnet status explicit on home and pricing, named the three public services,
clarified private integrations, replaced vague headings, and documented the 30-day
paid-result recovery window. Corrected MCP status to read the runtime setting:
production MCP is enabled and its server card returned 200. Status is catalog
availability, not a guarantee that each upstream provider is healthy.

## Validation

Ruff passed; 155 tests passed, 10 credentialed live tests skipped. Read-only
production checks confirmed Base Sepolia, ALLOW_MAINNET_X402=false, MCP enabled,
three public services, stylesheet edge caching, scoped Python-client access,
and external readiness monitoring. Herald's legacy local development database
was preserved twice on NVMe and replaced with a clean database at migration
`20261011_0004`. No AEU runtime changes or new AEU acceptance tests were part
of this ReachSocial audit.
