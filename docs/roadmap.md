# ReachSocial roadmap

## Paid MVP catalog completion — current state

The catalog contains 18 reviewed services. Two Instagram services are available
on Base Sepolia; fifteen integrations remain private; and Instagram current
stories is paused. Seventeen services are selected for the paid MVP: every
entry except current stories.

The shared release foundation is complete in code: maximum provider units are
reserved before payment settlement, uncertain provider use remains held for
reconciliation, provider caches have entry and byte limits, unused runtime state
is pruned safely, oversized bodies and payment headers are rejected before x402
parsing, and ScrapeCreators async work records dispatch before execution. The
production dependency audit is clean after updating `multidict` to 6.9.1.

The bounded 2026-10-11 provider run passed thirteen new or renewed
ScrapeCreators contracts at one credit each: X profile/post/feed, TikTok
profile/video/feed, Instagram feed/highlight, YouTube channel/video/feed,
Facebook profile, and Reddit post. It used a 100-credit ledger and left 6,812
provider credits, including the protected 1,000-credit InstaGet reserve.

The current public-mainnet release dependencies are:

1. `linkedin.profile` now uses ScrapeCreators as a private integration, but
   three fresh profiles returned `not_found`, including the provider's
   documented example. Hold public release until a successful bounded sample,
   protected async flow, recovery, and fresh real-USDC acceptance pass.
2. Each private service, including `news.person`, still needs its own paid
   recovery acceptance and 24-hour reconciliation before public promotion.

After those dependencies clear, release one stage at a time. For each stage:
recheck the live provider balance and 1,000-credit reserve, deploy the immutable
commit, run one real-USDC payment and recovery for each newly public service,
reconcile receipts and provider attempts, and observe for 24 hours. Pause new
payments on any unexplained settlement or consumption difference while keeping
paid-result recovery and accepted-job completion available.

## Base mainnet USDC launch gate

**Status (2026-10-11):** ReachSocial is live with authenticated B2B access,
MCP discovery, and anonymous x402 challenges on Base Sepolia. The earlier
Base-mainnet canary and three-route acceptance settled and recovered their
results, but the LinkedIn acceptance covered the retired Apify path. The handler
is disarmed and general Base-mainnet sales remain intentionally blocked.

**Audit follow-up completed:** [the prelaunch audit](prelaunch-audit-2026-10-11.md)
found and resolved shared-credit accounting, SDK edge access, recovery-key
strength, and external monitoring gaps. General mainnet sales remain disabled
until the final release decision.

Do not set `X402_NETWORK=eip155:8453` or `ALLOW_MAINNET_X402=true` until every
item below is complete and recorded in the release notes.

1. **Provider credits and cost policy — completed in code, recheck before
   release.** Instagram profile and post use a documented replacement-price
   cost of 1,880 micro-USD per credited attempt, verified with live endpoint
   consumption. This is explicitly not called a purchased invoice. The checked
   balance was 6,825 credits before the catalog-completion provider run;
   reserve 1,000 for InstaGet and set
   the protected balance configuration immediately before release. Public
   capacity is reserved durably before a mainnet provider call. A live,
   account-wide balance check now runs before each public ScrapeCreators
   settlement and fails closed if provider capacity cannot be verified. See
   [provider contract status](provider-contract-status.md) and
   [public payment operations](public-payment-operations.md).
2. **Rotate the CDP credential — completed 2026-10-11.** The exposed CDP API
   key pair was replaced in CDP and installed through a one-time hidden-input
   transit into the protected runtime configuration. The transit file was
   deleted after installation, and the restarted hosted service returned a
   valid unpaid x402 quote. Facilitator-authenticated settlement remains part
   of the independent real-USDC acceptance below.
3. **Merchant-wallet custody and recovery — completed 2026-10-11.** The
   replacement receiving wallet was restored in a separate owner-controlled
   local wallet installation and signed a fresh EIP-191 non-payment challenge.
   The local verifier retained only the address, verification time, and
   challenge hash; it never received the recovery phrase or raw signature.
   Production payment quotes now name the replacement address. The buyer
   wallet recovery check remains a separate control.
4. **Operations rehearsal — completed 2026-10-11.** The isolated restore drill
   passed for both production databases and application startups. The hosted
   emergency-pause drill blocked a new payment before challenge and preserved
   recovery of an existing settled result. An isolated provider-outage rehearsal
   confirmed one replacement credit and persisted-run recovery. The off-host
   DigitalOcean recovery path created and removed a temporary volume from the
   newest `tor1` production snapshot. The merchant returned $0.05 Base-USDC to
   the independent buyer and the exact transfer was reconciled. A local
   receipt-parser bug occurred after broadcast, not in payment execution; it
   is fixed and regression-tested. Ambiguous facilitator outcomes must remain
   `reconciliation_required`; no automatic payment retry is allowed.
5. **Independent real-USDC acceptance — completed 2026-10-11 for the prior provider mix.** A second
   buyer completed one Base-native-USDC payment for each launch route: $0.05
   Instagram profile, $0.05 Instagram post, and $0.10 asynchronous LinkedIn
   profile. The LinkedIn evidence covered the retired Apify route and must not
   be used to release its ScrapeCreators replacement. Base receipts, durable settlement records, one-time route
   reservations, provider consumption, paid-result recovery, and LinkedIn
   protected polling all reconciled. Automated tests cover wrong
   network/token/amount rejection and restart recovery. The protected
   reconciliation record retains the transaction evidence without payment
   signatures, job tokens, source URLs, or recovery material.
6. **Make the release decision.** Review the evidence, set the mainnet network
   and explicit allow flag, deploy, and verify all public discovery and payment
   information. Keep the $5 daily upstream-cost ceiling, current rate and
   concurrency limits, and the stricter verified credit budget for the first
   24 hours.

The application refuses a Base-mainnet configuration unless the allow flag is
set and every public service has a positive verified upstream cost. That guard
is necessary but does not replace the operational checks above.

## Mainnet canary evidence

**2026-10-11:** The isolated Base-mainnet canary settled one five-cent native
USDC payment from its named buyer for `instagram.profile`. The durable receipt,
successful normalized service result, and exactly one successful provider
attempt were reconciled. The regular public x402 routes remain on Base Sepolia;
this evidence does not authorize general Base-mainnet sales. The durable
payment receipt and canary reservation are retained; the linked provider and
request evidence must be exported into the protected reconciliation record
before ordinary operational retention removes their rows.

## Restore and backup evidence

**2026-10-11:** The latest encrypted Restic snapshot was restored under an
isolated NVMe verification path. ReachSocial's SQLite integrity check and
isolated application startup passed. AEU's PostgreSQL custom dump restored to
a temporary database with 16 public tables, and an isolated AEU container
started successfully against it. The temporary containers and database were
removed after the drill; the protected restore copy remains on NVMe for the
retention window.

Nightly Restic backup completed on 2026-10-10. DigitalOcean volume snapshots
are also scheduled weekly with four retained copies. On 2026-10-11, the newest
`tor1` production snapshot was restored into a temporary volume through the
DigitalOcean API, checked, and deleted without attaching it or touching
production.
