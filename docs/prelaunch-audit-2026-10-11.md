# Prelaunch audit — 2026-10-11

## Decision

The owner approved Base-mainnet release on 2026-10-11 for the two accepted
public Instagram services. The protected runtime now uses `eip155:8453` with a
fresh 6,812-credit baseline and a verified unpaid native-USDC $0.05 challenge.
No transfer or provider call was made by that release check. Earlier acceptance
and refund evidence remains valid for the routes and providers that produced it.
All private integrations remain outside public payment; their unresolved
dependencies are in [the roadmap](roadmap.md).

## Implemented API coverage

The runtime catalog has 18 services: 2 available, 15 private, and 1 paused.
Thirteen release-contract samples passed on ScrapeCreators, but
the public catalog remains intentionally limited to the two services that
completed its released stage:

| Platform | Public | Private / explicitly entitled B2B |
| --- | --- | --- |
| Instagram | profile, post | feed |
| X | — | profile, post, feed (public posts, not guaranteed latest) |
| TikTok | — | profile, video, feed |
| YouTube | — | channel, video, feed |

LinkedIn profile now uses ScrapeCreators as a private integration, but three
samples returned `not_found`; it remains held from public paid acceptance.
Private `news.person` uses GDELT. Its initial upstream rate limit cleared on a
bounded retry, which passed with its reviewed zero-cost classification.
Facebook profile, Reddit post, and Instagram highlight have working adapters
and passed provider contracts; they are also private integrations until their
paid public stages are eligible. Instagram current stories is paused. No active
catalog service uses Apify, and production has no queued or running Apify jobs.

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
4. **Monitoring — resolved.** System-wide application alerts latch an in-process
   pause for every new payment challenge and make `/readyz` return 503. Repeated
   retryable failures in one provider route isolate that service before payment;
   `/readyz` remains 200 and reports the degraded service. Paid recovery and
   accepted background jobs remain available. A three-region DigitalOcean
   uptime check watches `/readyz`; global failure and TLS-expiry policies notify
   the verified DigitalOcean account email.

## Security review scope and observations

Reviewed auth, payment hooks, recovery, credit reservations, URL normalization,
logging, process-local limits/cache, container/ingress configuration, and retention.
Scrypt API-key hashing, constant-time admin-token comparison, explicit client
entitlements, protected job polling, durable payment replay records, and uncertain
settlement state are implemented. Payment and operational responses default to
no-store. The app runs as a non-root container user; port 8000 is not published
on the host. Caddy normalizes forwarded client addresses.

This is not a penetration test. The production dependency audit is clean after
updating `multidict` to 6.9.1. Unauthenticated CPU abuse beyond the configured
body/header limits, multi-process races, host firewall configuration, and all
external-provider failure modes are not certified by this review. Process-local
rate, concurrency, and in-flight spend state assumes the current single-process
runtime; do not add workers or replicas without shared enforcement. Runtime
cache storage now has LRU entry/byte bounds, and idle rate-limit identities and
unheld idempotency locks are pruned.
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

Made network status explicit on home and pricing, named the public services,
clarified private integrations and public-release holds, replaced vague headings,
and documented the 30-day paid-result recovery window. Corrected MCP status to
read the runtime setting:
production MCP is enabled and its server card returned 200. Status is catalog
availability, not a guarantee that each upstream provider is healthy.

## Validation

The original audit passed its code suite; the catalog-completion update adds
bounded cache, body-limit, provider-dispatch, and new-adapter coverage. Its
final local result was 164 passed and 17 credential-gated live tests skipped;
the production dependency audit found no known vulnerabilities. Release checks
confirmed Base mainnet, `ALLOW_MAINNET_X402=true`, MCP enabled, an exact unpaid
native-USDC challenge, stylesheet edge caching, scoped Python-client access,
and external readiness monitoring.
Herald's legacy local development database was preserved twice on NVMe and
replaced with a clean database at migration `20261011_0004`. No AEU runtime
changes or new AEU acceptance tests were part of this ReachSocial audit.
