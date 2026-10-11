# ReachSocial roadmap

## Base mainnet USDC launch gate

**Status (2026-10-11):** ReachSocial is live with authenticated B2B access,
MCP discovery, and anonymous x402 challenges on Base Sepolia. One bounded
Base-mainnet USDC canary and a separate independent three-route acceptance
settled and recovered their results. The acceptance handler is disarmed;
general Base-mainnet sales remain intentionally blocked.

Do not set `X402_NETWORK=eip155:8453` or `ALLOW_MAINNET_X402=true` until every
item below is complete and recorded in the release notes.

1. **Provider credits and cost policy — completed in code, recheck before
   release.** Instagram profile and post use a documented replacement-price
   cost of 1,880 micro-USD per credited attempt, verified with live endpoint
   consumption. This is explicitly not called a purchased invoice. The checked
   balance was 6,827 credits on 2026-10-11; reserve 1,000 for InstaGet and set
   the protected balance configuration immediately before release. Public
   capacity is reserved durably before a mainnet provider call. See
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
4. **Operations rehearsal — refund outstanding.** The isolated restore drill
   has passed for both production databases and application startups. The
   hosted emergency-pause drill blocked a new payment before challenge and
   preserved recovery of an existing settled result. An isolated provider-outage
   rehearsal confirmed one replacement credit and persisted-run recovery. The
   off-host DigitalOcean recovery path created and removed a temporary volume
   from the newest `tor1` production snapshot. Rehearse one merchant-signed
   refund before release. Ambiguous facilitator outcomes must remain
   `reconciliation_required`; no automatic payment retry is allowed.
5. **Independent real-USDC acceptance — completed 2026-10-11.** A second
   buyer completed one Base-native-USDC payment for each launch route: $0.05
   Instagram profile, $0.05 Instagram post, and $0.10 asynchronous LinkedIn
   profile. Base receipts, durable settlement records, one-time route
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

Nightly Restic backup completed on 2026-10-10. The deployment documentation
expects weekly DigitalOcean volume snapshots, but this host currently has no
read-only `doctl` credential to list and verify them. Provide a least-privilege
read-only DigitalOcean token or an owner-side snapshot listing before claiming
off-host snapshot recovery is verified.
