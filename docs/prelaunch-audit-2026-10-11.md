# Prelaunch audit — 2026-10-11

## Decision

Keep general Base-mainnet sales disabled. Earlier acceptance and refund evidence
remains valid, but “all preflight gates complete” overstated the scope of those
checks. This source review and read-only hosted audit found the release holds
below. No new paid provider requests or transfers were made.

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

## Release holds

1. **Shared credit budget — high.** `credit_budget._committed_units` counts public
   payment reservations only. InstaGet/private usage or other users of the same
   provider key can drain the shared account without reducing public capacity.
   There is no freshness deadline for the operator-observed balance. Add a
   timestamped balance baseline and account-wide consumption reconciliation,
   with fail-closed behavior when stale, before claiming reserve protection.
   Replacing the balance also subtracts historical public consumption again:
   conservative, but inaccurate. A balance reset must have an accounting epoch.
2. **Agent access at Cloudflare — high for launch usability.** GET /status.json
   with curl returned 200; Python urllib and curl with Python-urllib/3.12 both
   returned 403 (Cloudflare 1010). Review the relevant edge rule and validate
   ordinary SDK clients on discovery and API paths. Do not disable unrelated
   protections globally. This audit did not modify Cloudflare rules.
3. **Recovery key strength — medium.** Paid recovery is a bearer capability:
   the original idempotency key plus matching input recovers the result/job.
   `_validate_idempotency_key` currently accepts 1–255 characters; randomness
   is documented, not enforced. New anonymous payments need a strong-key
   requirement and abuse limits, preserving retrieval of existing paid records.
   The website now tells callers to keep the key private and use a fresh UUID.
4. **Monitoring — medium.** `alerts.py` emits warnings to application logs every
   minute. It does not deliver alerts externally or automatically pause new
   payments. Arrange a monitored release window and alert delivery/reconciliation
   procedure before calling the first 24 hours covered.

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
The ingress container currently receives the shared runtime env_file; reducing it
to ingress-only settings is worthwhile hardening.

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

Ruff passed; 150 tests passed, 10 credentialed live tests skipped. Read-only
production checks confirmed Base Sepolia, ALLOW_MAINNET_X402=false, MCP enabled,
three public services, and stylesheet edge caching. No AEU runtime changes or
new AEU acceptance tests were part of this ReachSocial audit.
