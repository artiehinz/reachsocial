# Self-service MCP and catalog release

Owner-approved implementation plan, 2026-10-14. This document records release
state, not a claim that unfinished acceptance has passed.

## Decisions and invariants

- REST remains anonymous x402. MCP adds wallet SIWE login, OAuth, and approval
  of each $0.05 request in an owner-controlled browser wallet.
- No prepaid balance, delegated spending, server-held wallets, or public B2B-key issuance.
- Preserve B2B entitlements, existing result recovery, the 1,000-credit reserve,
  $5 daily upstream ceiling, single-process deployment, and NVMe/DO storage.
- Seven additional social routes ship in stages: Instagram feed/highlight;
  YouTube channel/video/feed; Facebook profile/Reddit post. LinkedIn, public
  Person News, and current Instagram stories remain on hold. AEU is unchanged.
- Directories use `artemhinz2@gmail.com`, explicitly approved by the owner.

## Implementation and rollout

- Concrete OpenAPI paid operations and guidance derive from the public catalog;
  never include private services as paid operations.
- OAuth uses the installed MCP SDK protocol handlers, durable hashed state,
  PKCE, one-time SIWE challenges, opaque short-lived access tokens, rotating
  refresh tokens, revocation, and constrained client registration/metadata fetch.
- `OAUTH_ENABLED` and `MCP_PAYMENT_APPROVAL_ENABLED` default false. They must
  not be activated merely because a database migration or static card exists.
- `/account` manages connections and recent requests. `/pay/{request_id}` uses
  the tested browser helper. A request key binds wallet, OAuth client, service,
  input and price. Unpaid requests expire after 30 minutes; approval capabilities
  after five minutes. Signed attempts are never automatically reissued.
- OAuth codes/tokens, browser sessions, and approval capabilities are hashed.
  Wallet signatures and x402 payment signatures are never persisted.
- `PUBLIC_PROVIDER_MAX_ATTEMPTS=1` enforces the one-attempt acceptance limit for
  public execution. Default 3 preserves each service's existing lower retry bound.
- The browser bundle is generated from the tested TypeScript source using
  `npm run build:browser`; CI rejects a stale committed bundle.

## Acceptance ledger and gates

The existing local provider ledger was read without printing targets or keys:
100-credit original cap, 33 conservative credits consumed, 38 recorded events.
This is historical provider evidence, not a fresh account-wide balance check.

The direct-MCP case below already consumed one $0.05 payment and one provider
credit. The remaining batch may consume at most **$0.45 USDC and 19 provider
credits**, bounded further by the original $2/100-credit allowance. Reconcile
payment receipts before spending; count retries and failed charged calls. The
nine remaining allocations are standalone browser, AgentCash, and the seven
additional services. Wallet signing remains local to the owner. No automatic
top-ups.

Release gates still requiring recorded evidence:

Latest deployment, scheduled-monitoring, real-HTTP SDK, synthetic browser,
and unpaid production evidence: [2026-10-15 client acceptance](unpaid-client-acceptance-2026-10-15.md).

- [x] Current budget reconciliation and live provider balance baseline (see below).
- [x] Root-protected nightly-backup restore with the additive OAuth/request tables.
  Passed 2026-10-15 at 19:40:30 UTC through the deployment user's fixed
  `sudo -n /usr/local/sbin/reachsocial-ops verify-restore` action. Both databases
  restored into isolated, no-network containers; application/OAuth/MCP checks
  and cleanup passed. See [operations evidence](operations.md#evidence-and-remaining-acceptance).
- [ ] Full OAuth/MCP integration and browser security checks, including Smithery compatibility.
- [ ] One bounded browser payment and same-key recovery.
- [x] One bounded owner direct-MCP approval/payment/recovery and initial OAuth authorization. Independent client compatibility remains open.
- [ ] One bounded AgentCash payment/recovery, preserving the original key.
- [ ] Reconcile the six existing X/TikTok transfers and their observation evidence.
- [ ] Stage A: Instagram feed/highlight paid acceptance, then 24-hour observation.
- [ ] Stage B: YouTube channel/video/feed paid acceptance, then 24-hour observation.
- [ ] Stage C: Facebook profile/Reddit post paid acceptance, then 24-hour observation.
- [ ] Official MCP Registry domain HTTP verification and publication.
- [ ] Smithery OAuth acceptance; Glama claim/health; follow up existing submissions.
- [ ] AgentCash/x402scan owner SIWX registration and indexing; Bazaar indexing.
- [ ] Public docs repository retained-history cleanup before visibility changes.

Directory details and evidence are in [the tracker](registry-submissions/README.md).
Submitted, approved, and indexed are separate statuses. Do not duplicate the
owner's Glama, MCP Market, or MCPservers.org submissions. External approval and
observation windows cannot be marked complete by automated unit tests.

## Operations

Use unpaid discovery/auth probes for routine monitoring; never make paid
provider calls as health checks. Keep uncertain payments for reconciliation,
retain paid retrieval when new payments are paused, and isolate OAuth failure
from public REST. Manual refunds, exceptional reconciliation, and security
incidents remain operator tasks.

Keep the public documentation repository private pending its documented
retained-history cleanup. Neither application source nor operational evidence
belongs in that repository. Do not repeat completed wallet-custody or refund
ceremonies without evidence of a new issue.

## Read-only production baseline — 2026-10-14

Production image: `9be5c68a730965236ee9301c19b97b81a34222d8`.
Live ScrapeCreators balance: 6,782 credits; reserve: 1,000; upstream ceiling:
5,000,000 micro-USD/day. No unfinished queued/running jobs were found.
There are 11 settled receipts totaling $0.60 and two canceled-before-settlement
receipts totaling $0.10; no uncertain receipt status was present in this read.
This aggregate is a conservative spending baseline, not attribution of every
receipt to this release batch.

All six owner-supplied X/TikTok transactions were verified independently on
Base RPC: successful receipt, exact native-USDC contract, expected buyer and
merchant, exactly 50,000 atomic units. Each production receipt is settled and
links to one recorded provider attempt consuming one credit. This closes their
receipt/provider reconciliation, but does not establish a clean 24-hour
observation window for the newest deployment.

The deployment account now has the three fixed sudo actions from the reviewed
[operations package](operations.md), installed through the owner console on
2026-10-15. Fresh encrypted backup and full restore verification passed with the
corrected verifier in operations version `a809ebd`. Routine backup and restore
checks no longer need the root console. Pre-deployment SQLite snapshots are separately accessible
through the application container and can be restored without expanded sudo.

The public docs repository was unexpectedly public with retained backend
history still accessible. It was returned to private; historical-object cleanup
remains pending. See the dedicated cleanup record.

## Isolated restore and transport verification

Restored the configured pre-deployment snapshot `reachsocial-20261014T163544Z.db`
into a protected ignored directory on Herald NVMe. SQLite integrity passed before
and after migration to `20261014_0005`; all 13 historical receipts remained.
Isolated application startup, OAuth metadata, account page, authenticated MCP
challenge, and static server card returned expected responses, with payments
and provider credentials disabled. This does not replace verification of the
root-protected nightly Restic repository.

The real local MCP HTTP test now covers initialize, tools/list, an OAuth-owned
Instagram payment intent, and request retrieval without a transfer/provider call.
It found and fixed the mounted MCP session-manager lifespan integration.
Transport host/origin checks now use the configured public origin explicitly.

`OAUTH_VALIDATION_WALLETS` can restrict login/token use to the owner during live
acceptance. Do not clear this gate or advertise general self-service until the
browser, direct-MCP, and client payment checks pass.

## Owner-only direct-MCP acceptance

After deploying the tested commit, keep public self-service gated by
`OAUTH_VALIDATION_WALLETS` and set `PUBLIC_PROVIDER_MAX_ATTEMPTS=1` before any
owner approval. Confirm the current provider balance and batch ledger first.
The browser and AgentCash cases remain separate gates.

Run on the owner's desktop computer with its injected wallet installed (not a
remote shell whose loopback callback the browser cannot reach):

```bash
cd /mnt/instaget-nvme/herald-work/reachsocial
.venv/bin/python scripts/mcp_browser_acceptance.py \
  --expected-pay-to 0x76bCc44696A4c67579A6aF2F25CF953BE0931E38 \
  --max-total-atomic 50000 \
  --confirm-mainnet-payments
```

The browser signs a non-payment login, grants the named client access, then
separately asks for one $0.05 Instagram-profile payment. The script never asks
for a recovery phrase. It saves the original client and request identifiers in
`data/mcp-browser-acceptance.json` with mode 0600 before opening payment approval.
If interrupted, rerun with the same checkpoint. Do not delete it or replace its
key to retry an uncertain charge. Tokens remain in memory; no wallet secrets,
payment signatures, or profile results are written to the checkpoint.

Success requires a settled receipt plus two matching request retrievals. After
owner acceptance, independently reconcile the transaction and provider-attempt
count before recording a pass. A successful script alone does not prove the
provider-credit delta or complete the fresh-client directory acceptance gates.


## Gated production deployment — 2026-10-14

PR #16 merged and deployed immutable commit
`4b586f1ba6013e2fad2f3fc8579b436820a17a18`. CI passed secret scanning, Python
(208 passed / 17 credentialed skips), TypeScript and frontend checks (33 passed),
image build, and the configured HIGH/CRITICAL fixed-vulnerability gate.

OAuth and MCP approval are enabled only for the owner buyer wallet
`0xcf8fD9bd415C36326597E8079fCb3125FE2dB369`, with public provider attempts limited
to one. No other new user can sign in yet. The eight existing public REST
services remain available; all seven staged additions remain private. Duplicate
identical image entries in the runtime env were consolidated without exposing
runtime secrets. No AEU configuration was changed.

Post-enable checks: public health/readiness 200, account page 200 with no-store,
authorization-server and protected-resource metadata 200, unauthenticated MCP
401 with resource-metadata challenge, non-owner SIWE login 403. The container is
healthy with zero restarts. One initial health probe returned 502 during the
container replacement and recovered; this is not a zero-downtime rollout.

Live balance remains 6,782 credits, with the 1,000-credit reserve. Receipt totals
remain 11 settled / $0.60 and two canceled-before-settlement / $0.10. No new paid
call or transfer was made. Owner browser acceptance is the next live gate; do
not remove the allowlist merely because metadata and unpaid probes pass.

Before general availability, also complete unpaid scheduled auth/readiness
monitoring and alerts for stalled MCP intents, retention review of expired
intent state (preserving uncertain charges), and account-cookie/privacy wording.
Bazaar discovery integration/indexing and real directory-client interoperability
remain unverified. These are not closed by the current unit tests.


## Owner direct-MCP acceptance passed — 2026-10-14

The owner completed wallet sign-in, OAuth consent, MCP intent creation, browser
approval, and repeated MCP result retrieval using the original checkpoint.
Service: `instagram.profile`; amount: 50,000 native Base-USDC atomic units ($0.05).
Transaction: `0x0698ad8794fbc8741b1b871fe548262b5784ffbca3951e713645899a45e643a9`.
Request: `1c786c05bb80e160a34775e36b7dae8996f0e873c0908fbebd5c16cc8409d7c1`.

Independent Base RPC verification confirmed successful settlement in block
52,608,395, with exactly one matching native-USDC transfer between the expected
buyer and merchant. Production has one matching settled receipt for five cents,
one provider attempt consuming one credit, and the correct OAuth wallet owner.
The live account balance decreased from 6,782 to 6,781. The script reported
matching recovered results; the receipt and attempt counts show no duplicate
charge or execution during recovery.

This batch has consumed $0.05 of its original $0.50 allocation and one of its 20 provider
credits. The local cumulative provider ledger now records 34 credits against
its 100-credit cap. Production settled receipt totals are 12 / $0.65; the two
canceled-before-settlement records remain unchanged. Count this flow once, not
as separate browser and MCP purchases. The standalone browser and AgentCash
acceptance allocations remain unused.

The checkpoint is retained. During setup, its ownership was repaired and a
suspended duplicate local listener was terminated; neither required replacing
the request key. MetaMask's site-connected account differed from the selected
account, causing the owner-only gate to reject login until the buyer account
was reconnected. Improve account selection/disconnect guidance and display the
actual auth rejection reason before general availability.

Owner-only access remains enabled. This closes the direct-MCP paid-flow gate,
not directory interoperability, standalone browser acceptance, staged catalog
promotion, monitoring/retention work, or the required observation windows.

## Restricted private-service acceptance lane — implemented, disabled

The next seven services cannot be exercised through the public acceptance
script while they remain private. The application now has a separate disabled
lane for a single owner-controlled stage:

- It accepts only explicitly configured private synchronous five-cent
  ScrapeCreators services and one configured owner wallet.
- It verifies Base mainnet, native Base-USDC, price, receiver, current
  account-wide provider balance, the 1,000-credit reserve, margin, and a
  one-provider-attempt limit before settlement.
- It uses the ordinary receipt, execution, idempotency, and 30-day recovery
  paths, but does not appear in public service discovery, OpenAPI paid
  operations, or the static MCP card.
- An opaque run ID permits one settled payment per service. Same-key recovery
  returns the stored result; a second payment or B2B/service-credit bypass is
  rejected.

Set only one release stage in the protected runtime environment, run its
dry-run challenge first, then make the owner-approved payment. Disable the
lane immediately after the stage. The exact procedure is in
[public payment operations](public-payment-operations.md#restricted-private-service-acceptance).
No stage has passed merely because this lane is present in the deployed image.
