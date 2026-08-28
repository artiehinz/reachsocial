# ReachSocial readiness and next release gates

Updated: 2026-08-27

## Current catalog truth

| State | Services |
| --- | --- |
| Available | `instagram.profile`, `instagram.post`, `linkedin.profile` |
| Private | `news.person`, `instagram.feed`, `x.profile`, `x.feed`, `x.post`, `tiktok.profile`, `tiktok.feed`, `tiktok.video`, `youtube.channel`, `youtube.feed`, `youtube.video` |
| Paused | `instagram.stories` |
| Planned | `facebook.profile`, `reddit.post` |

`GET /v1/services` is intentionally the executable subset. `GET /v1/catalog`
is the reviewed product roadmap. The ScrapeCreators engineering inventory has
178 operations, of which 173 remain unreviewed; it is not a public catalog.

The private services above have reviewed adapters, normalized fixtures, and
credential-gated live coverage. They are executable only for explicitly
entitled internal clients. Public sale remains blocked on purchased-plan
reconciliation and margin-safe pricing; that separate sales gate does not
block InstaGet's funded internal MVP use.

## URL resolution contract

`POST /v1/resolve` is the protected, provider-neutral URL authority shared with
InstaGet. It canonicalizes reviewed Instagram, X, TikTok, LinkedIn, YouTube,
Facebook, and Reddit URL shapes and returns the matching catalog service,
execution mode, lifecycle status, and whether the calling client may execute
it. Known but unreviewed URL shapes fail closed instead of guessing a service.

Resolution does not make a catalog entry executable. Catalog state, client
entitlements, and the normal execution endpoint remain independent gates.

`x.feed` now uses the reviewed bounded ScrapeCreators route; the older Apify
route remains rejected. ScrapeCreators documents this endpoint as returning a
publicly available popular-post set rather than a reliably chronological feed,
so the catalog and consumer UI call these "public posts," not "latest posts."
`instagram.stories` has no approved bounded provider.

## Agent and MCP readiness

REST is the current agent-ready surface:

- typed, service-specific OpenAPI input schemas and normalized output schemas;
- `/llms.txt`, `/agent.md`, `/.well-known/api-catalog`, `/robots.txt`, and a
  sitemap;
- an honest MCP Server Card at `/.well-known/mcp.json` when MCP is enabled;
- explicit executable versus validation/planned/paused catalog states;
- B2B Bearer authentication and Base Sepolia x402 challenges;
- durable async job submission/polling and replacement credits; and
- idempotency, replay protection, entitlements, limits, cost accounting, and
  owner metrics.

The MCP implementation now generates exact per-service tools, sends
long-running services through durable jobs, and authorizes job polling by the
calling B2B client. It remains disabled in production. Enabling it requires a
scoped MCP client, live protocol smoke test, rate/concurrency acceptance, and
operational monitoring. Public unpaid MCP is not planned.

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
ReachSocial sale and reconciliation against the actual purchased pack remain a
separate later approval.

## Ordered next release work

1. Run the dedicated Base Sepolia paid API smoke command and reconcile its
   transaction, receipt, request, and single provider attempt.
2. Monitor the internal four-network Herald flow, cache hit rate, provider cost,
   media relay failures, and consumer Usage settlement.
3. Run one guarded LinkedIn submission/poll/recovery acceptance against an
   approved public profile before enabling its independent InstaGet flag.
4. Reconcile the actual purchased ScrapeCreators plan for later public
   ReachSocial pricing; this is not an internal MVP gate.
5. Enable authenticated B2B MCP after its independent live protocol and limit
   tests.
6. Expand the provider-neutral catalog in batches: Instagram/TikTok comments
   and transcripts, Facebook/Reddit/LinkedIn company/post, then
   independently reviewed long-tail platforms.

Mainnet, public x402 MCP, prepaid balances, and broad directory submissions
remain later gates. Encrypted off-Droplet backup and a restore drill continue
to block Base mainnet.
