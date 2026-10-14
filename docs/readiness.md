# ReachSocial readiness and next release gates

Remaining work after owner acceptance: [onboarding and release plan](onboarding-remaining-plan.md).

Current self-service implementation and remaining release gates: [self-service release](self-service-release.md).

Updated: 2026-10-14

## Current catalog truth

| State | Services |
| --- | --- |
| Available | `instagram.profile`, `instagram.post`, `x.profile`, `x.post`, `x.feed`, `tiktok.profile`, `tiktok.feed`, `tiktok.video` |
| Private | `news.person`, `instagram.feed`, `instagram.highlight`, `youtube.channel`, `youtube.feed`, `youtube.video`, `facebook.profile`, `reddit.post` |
| On hold | `linkedin.profile`, `instagram.stories` |

`GET /v1/services` is intentionally the executable subset. `GET /v1/catalog`
is the reviewed product roadmap. The ScrapeCreators engineering inventory has
178 operations, of which 173 remain unreviewed; it is not a public catalog.

The private services above have reviewed adapters, normalized fixtures, and
credential-gated live coverage. They are executable only for explicitly
entitled internal clients. A bounded 2026-10-11 contract run passed thirteen
ScrapeCreators services, including the Facebook, Reddit, and saved-highlight
adapters added in this release. Their one-credit replacement-cost basis is
recorded as 1,880 micro-USD per attempt. This is documented replacement pricing,
not a purchased invoice.

A fresh 2026-10-11 recheck passed all fourteen non-LinkedIn private services,
including Person News under its reviewed zero-cost classification. The supplied
saved highlight was unavailable, but the provider's documented saved-highlight
sample passed. The protected ledger now records 33 conservative ScrapeCreators
units out of its 100-credit allowance; the live balance was 6,799 credits, with
the 1,000-credit InstaGet reserve intact.

Person News is enabled for approved API-key clients, including InstaGet-Herald,
by owner request on 2026-10-14. Anonymous paid execution remains disabled.
LinkedIn remains disabled for new public and API-key requests.
Production GDELT calls previously returned HTTP 429 before settlement;
ScrapeCreators LinkedIn samples returned `not_found`. Historical recovery and
accepted jobs remain separate from new-service availability.

The owner reported six successful Base-USDC settlements with recovery for
X profile/post/feed and TikTok profile/video/feed, totaling $0.30. Together
with Instagram profile/post, eight current services have paid acceptance.
The new batch still needs its 24-hour observation and receipt/provider
reconciliation. Seven private integrations still need paid acceptance before
public promotion. No further paid tests were performed for this status update.

On 2026-10-13, three logical `instagram.profile` requests produced six retry
attempt failures while terminal `instagram.feed` lookups also returned
`not_found`. The original aggregate provider alarm paused every public payment
route for roughly fifteen minutes even though the host, website, proxy, and
unrelated services remained healthy. Runtime isolation now counts distinct
logical retryable failures, excludes terminal content results, and opens a
pre-payment circuit only for the affected public service. Global credit,
settlement, database, job, memory, and disk safeguards remain global.

## URL resolution contract

`POST /v1/resolve` is the protected, provider-neutral URL authority shared with
InstaGet. It canonicalizes reviewed Instagram, X, TikTok, LinkedIn, YouTube,
Facebook, and Reddit URL shapes and returns the matching catalog service,
execution mode, lifecycle status, and whether the calling client may execute
it. Known but unreviewed URL shapes fail closed instead of guessing a service.

Resolution does not make a catalog entry executable. Catalog state, client
entitlements, and the normal execution endpoint remain independent gates.

`x.feed` uses the reviewed bounded ScrapeCreators route; the older Apify route
remains rejected. Saved Instagram highlight URLs resolve separately from current
stories. ScrapeCreators documents X's endpoint as returning a
publicly available popular-post set rather than a reliably chronological feed,
so the catalog and consumer UI call these "public posts," not "latest posts."
`instagram.stories` has no approved ScrapeCreators contract and remains paused.

## Agent and MCP readiness

REST is the current agent-ready surface:

- typed, service-specific OpenAPI input schemas and normalized output schemas;
- `/llms.txt`, `/agent.md`, `/.well-known/api-catalog`, `/robots.txt`, and a
  sitemap;
- an honest MCP Server Card at `/.well-known/mcp.json` when MCP is enabled;
- explicit available, private, planned, and paused catalog states;
- B2B Bearer authentication and Base-mainnet x402 challenges for the current
  eight-service batch;
- durable async job submission/polling and replacement credits; and
- idempotency, replay protection, entitlements, limits, cost accounting, and
  owner metrics.

The MCP implementation generates exact tools for the public catalog, sends
long-running services through durable jobs, and authorizes job polling by the
calling B2B client. Production enables authenticated MCP and its server card
was reachable on 2026-10-11. The next deployment must recheck authenticated
discovery, execution, entitlement denial, and protected polling before another
async service is released. Public unpaid MCP is not planned.

## InstaGet readiness

ReachSocial and InstaGet completed the four-network live contract matrix on
2026-08-27. The consumer repository has:

- strict schema `1.0`/normalization `v1` validation;
- a server-only client with no browser exposure or legacy-provider fallback;
- a strict consumer for the protected URL-resolution contract;
- sanitized profile/post fixtures;
- independent fail-closed switches for every routed Instagram, X, TikTok, and
  YouTube service;
- a guarded, one-call live-shadow command; and
- a dedicated `social` Celery queue and worker, isolated from rate-limited
  background news work.

Fresh profile/feed and post routing is code-ready for synchronous Instagram, X,
TikTok, and YouTube services. InstaGet now also has a durable asynchronous
consumer for `linkedin.profile`: it persists the ReachSocial job ID, polls with
the same authenticated client, reuses the submission idempotency key after a
transport timeout, and settles consumer Usage only after normalized success.
The independent LinkedIn flag remains off until a guarded live end-to-end
acceptance target is approved; the existing managed path stays in place while
that flag is off.

The deployment workflow scopes `InstaGet-Herald` to `news.person` plus the
twelve approved social profile/feed/post services and permits two concurrent
requests, matching InstaGet's parallel profile/feed worker.

ScrapeCreators currently documents one credit for each of the twelve endpoints
used by the four-network InstaGet flow. At its published Freelance price of $47
for 25,000 credits, a cache-miss request costs $0.00188; at the published
Business price of $497 for 500,000 credits, it costs $0.000994. A cold profile
flow makes two parallel requests (profile plus posts), so its upstream cost is
$0.00376 or $0.001988 at those respective plans. ScrapeCreators documents cache
hits as zero credits, and ReachSocial also retains its own bounded service
caches. Existing account credits are sufficient for the internal MVP. Public
ReachSocial sale uses documented replacement pricing; actual acquisition expense
is recorded separately. No purchase is required for existing-credit tests.

## Ordered next release work

1. Resolve the current ScrapeCreators LinkedIn `not_found` response, rerun its
   provider contract, then rerun submission, polling, restart, recovery, and
   a fresh real-USDC acceptance before restoring public availability.
2. Keep Person News private until its own paid recovery acceptance and public
   release stage pass. Its bounded zero-cost availability retry passed.
3. Recheck authenticated MCP discovery, entitlement denial, execution, and
   protected job polling on the deployed image.
4. Recheck the provider balance, retain the 1,000-credit reserve, and use the
   100-credit/$2 acceptance ledger before each staged public-mainnet release.
5. Promote only services that complete their paid recovery acceptance, then
   observe and reconcile each stage for 24 hours.

Self-service OAuth/MCP payment approval and directory publication are now tracked
in the self-service release plan. Prepaid balances remain out of scope. Eight synchronous services are active on Base mainnet; private services
still need their own release decision and evidence.

## Browser developer onboarding

The minimal browser onboarding flow is implemented in code: the homepage shows
a stored sanitized URL-to-JSON example, `/docs/api` renders one tested
TypeScript x402 helper, and an EIP-6963 readiness panel checks account, Base
network, and native Base-USDC balance without signing or sending an address to
ReachSocial. `/status.json` publishes non-secret x402 version, chain, asset,
decimals, and receiver metadata. The helper still verifies those facts against
the actual payment challenge before signing.

Cross-origin access is intentionally limited to status and executable-service
discovery, public synchronous execution, and paid-result recovery. Bearer,
admin, job-token, cookie, and service-credit surfaces do not receive CORS
permission. Production acceptance requires one bounded $0.05 Instagram profile
payment, stored-result recovery with the same key, and reconciliation showing
one transfer and one provider execution. This new browser acceptance has not
been completed; the older Python-client acceptance does not establish browser
wallet compatibility. The [onboarding audit](onboarding-audit-2026-10-14.md)
records UI, simulated payment, recovery, and CORS checks without spending.
