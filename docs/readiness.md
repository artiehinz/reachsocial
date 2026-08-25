# ReachSocial readiness and next release gates

Updated: 2026-08-24

## Current catalog truth

| State | Services |
| --- | --- |
| Available | `instagram.profile`, `instagram.post`, `linkedin.profile` |
| Validation | `x.profile`, `x.post`, `tiktok.profile`, `tiktok.feed`, `tiktok.video` |
| Paused | `instagram.stories`, `x.feed` |
| Planned | `youtube.video`, `facebook.profile`, `reddit.post` |

`GET /v1/services` is intentionally the executable subset. `GET /v1/catalog`
is the reviewed product roadmap. The ScrapeCreators engineering inventory has
178 operations, of which 173 remain unreviewed; it is not a public catalog.

The five ScrapeCreators validation services already have adapters, sanitized
normalization fixtures, and credential-gated live contract coverage. Their
shared release blocker is the real purchased credit price and dated cost
evidence. They remain non-executable until that value is recorded and their
margin-safe public price is accepted.

## URL resolution contract

`POST /v1/resolve` is the protected, provider-neutral URL authority shared with
InstaGet. It canonicalizes reviewed Instagram, X, TikTok, LinkedIn, YouTube,
Facebook, and Reddit URL shapes and returns the matching catalog service,
execution mode, lifecycle status, and whether the calling client may execute
it. Known but unreviewed URL shapes fail closed instead of guessing a service.

Resolution does not make a catalog entry executable. Catalog state, client
entitlements, and the normal execution endpoint remain independent gates.

`x.feed` remains paused because the bounded live Actor run returned sentinel
records rather than normalized posts. `instagram.stories` has no approved
bounded Actor. Neither is silently routed to another paid provider.

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

ReachSocial is contract-ready for an Instagram-only Herald shadow start, but
is not yet accepted for an InstaGet cutover. The consumer repository has:

- strict schema `1.0`/normalization `v1` validation;
- a server-only client with no browser exposure or legacy-provider fallback;
- a strict consumer for the protected URL-resolution contract;
- sanitized profile/post fixtures;
- independent fail-closed switches for every routed Instagram, X, TikTok, and
  LinkedIn service; and
- a guarded, one-call live-shadow command.

Fresh profile and post routing is code-ready for synchronous Instagram, X, and
TikTok services, but only Instagram is eligible for the first shadow. X and
TikTok remain dark until their ReachSocial catalog entries are promoted.
LinkedIn remains blocked in InstaGet until durable async job polling is wired;
it must not be sent through the synchronous execution path.

Before the first live InstaGet call, complete Instagram cost evidence, verify
the deployed ReachSocial revision and rollback state, then create a separate
`InstaGet-Herald` client entitled only to `instagram.profile` and
`instagram.post`. The raw key goes directly to protected Herald configuration.

After two representative calls pass, the next code cycle may connect a
comparison-only worker/task entry point. Public search, persistence, media
leases, Social Credits, and Production remain separate later approvals.

## Ordered next release work

1. Record the actual ScrapeCreators plan/pack economics and run the five
   bounded live contract tests. Promote only passing services.
2. Run the dedicated Base Sepolia paid API smoke command and reconcile its
   transaction, receipt, request, and single provider attempt.
3. Provision the scoped InstaGet Herald B2B client and complete two one-call
   Instagram shadow checks.
4. Exercise and soak the existing guarded InstaGet worker entry point; keep
   all public/write flags off.
5. Implement durable InstaGet polling for async ReachSocial jobs before any
   LinkedIn service flag can be enabled.
6. Enable authenticated B2B MCP after its independent live protocol and limit
   tests.
7. Expand the provider-neutral catalog in batches: Instagram/TikTok comments
   and transcripts, YouTube, Facebook/Reddit/LinkedIn company/post, then
   independently reviewed long-tail platforms.

Mainnet, public x402 MCP, prepaid balances, and broad directory submissions
remain later gates. Encrypted off-Droplet backup and a restore drill continue
to block Base mainnet.
