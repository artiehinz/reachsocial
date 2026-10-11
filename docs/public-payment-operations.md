# Public payment operations

This runbook covers the three public Base-USDC services: Instagram profile and
post at $0.05, and LinkedIn profile enrichment at $0.10. It is for the release
window only; it does not authorize another provider credit purchase, catalog
expansion, or an AEU payment mode.

## Capacity and cost policy

ScrapeCreators has a documented replacement-price basis of 1,880 micro-USD per
credit (the published $47 / 25,000-credit tier). The existing account balance
is not described as a purchased invoice. Its current cost basis is:

1. the documented replacement price;
2. live endpoint evidence that each Instagram profile or post attempt consumes
   one credit; and
3. a checked account balance recorded at launch preparation.

Record an actual acquisition expense separately when a pack is eventually
purchased. Do not rewrite replacement-price evidence as an invoice.

Before each public-mainnet deployment, check the balance with the protected
runtime environment:

```bash
uv run python scripts/check_scrapecreators_credit_balance.py --internal-reserve 1000
```

Set `SCRAPECREATORS_CREDIT_BALANCE` to the returned balance and retain
`SCRAPECREATORS_CREDIT_RESERVE=1000` for InstaGet. The application treats the
difference as public capacity, reserves the maximum retry cost before provider
execution, records actual charged units, and never tops up automatically. It
also retains the existing $5 daily upstream-cost cap, public request limits,
and provider concurrency limit.

The 2026-10-11 balance check returned 6,827 credits. This was a balance
observation, not an invoice or an authorization to buy credits. Recheck it
immediately before enabling mainnet so later InstaGet use is accounted for.

LinkedIn uses Apify rather than ScrapeCreators. The accepted actor has a
$0.05 total-charge cap and recorded a stable $0.018 cost. At a $0.10 sale
price, its worst permitted expense leaves the required $0.05 margin. The
worker persists the provider run reference before polling, so a restart polls
the existing run rather than creating a second paid run. Provider timeout,
unavailability, or internal failure makes exactly one replacement service
credit claimable by the job holder.

## Paid-result recovery

Anonymous paid calls must include a high-entropy `Idempotency-Key`. Reuse it
only with the same service and input. If the client loses the response, it may
repeat the original paid request with that key; the gateway lets the stored
result or existing job through without another transfer or provider call.

The client can also make this uncharged recovery request using the original
body and key:

```text
POST /v1/payments/recover/{service_id}
Idempotency-Key: <original-key>
{"input": <original-input>}
```

The recovery response includes only payment state plus the stored synchronous
result or async job state. It never returns a wallet phrase, raw payment
signature, provider credential, or job token. Paid synchronous results and
anonymous paid jobs are retained for 30 days. Keep the key until the result is
saved.

## Reconciliation, refunds, and provider failures

`payment_receipts` contain the payment hash, payer, network, transaction
reference, linked request or job, and replacement-credit amount. Raw payment
signatures and wallet recovery phrases are never retained.

If the facilitator reports a settlement failure after verification, ReachSocial
sets the receipt to `reconciliation_required`. It does not retry a transfer,
call the provider again, or label the payment canceled. Reconcile the on-chain
transaction and the receipt first, then either deliver the recoverable result,
issue the already-supported replacement credit for an eligible async provider
failure, or refund manually from the receiving wallet. Record the refund or
confirmed settlement transaction reference in the operator accounting record.

For a provider outage, pause new public payments, allow paid-result recovery
and queued accepted jobs to continue, then inspect `payment_receipts`,
`provider_attempts`, and `async_jobs`. Do not delete uncertain receipts.

## Emergency pause

`PUBLIC_PAYMENTS_PAUSED=true` stops new anonymous public x402 requests before
they receive a payment challenge. It does not block recovery or background work
for accepted jobs. Change only that value with the included script, then
recreate the ReachSocial app container using the normal deployment command:

```bash
uv run python scripts/set_public_payment_pause.py --env-file <protected-runtime-env> --pause
# run the normal deployment/recreate command for the exact existing image
```

Use `--resume` only after provider capacity, settlement reconciliation, and
worker health are confirmed. The first 24-hour release window must watch
settlement states, stuck jobs, provider units, available public credits, and
receipt/provider reconciliation differences. Pause new payments on any
unexplained difference while preserving retrieval and accepted-job completion.

## Wallet custody and launch release

The buyer wallet recovery test and the merchant receiving wallet are separate
controls. Before public sales, the receiving-wallet owner must restore that
wallet in a separate local wallet installation, confirm the configured
`X402_PAY_TO` address, and sign a fresh non-payment challenge. Keep the recovery
material only in the owner-controlled password manager or hardware-wallet
backup; do not place it on the Droplet, in CI, or in a support ticket.

From the owner's local ReachSocial checkout, run the loopback-only verifier and
open the printed address in that same wallet browser/profile:

```bash
uv run python scripts/merchant_wallet_custody_console.py \
  --expected-address <X402_PAY_TO-address>
```

It expires after ten minutes, validates an EIP-191 message signature locally,
and stores only the address, verification time, and challenge hash under the
owner's local state directory. It never asks for, reads, or retains a recovery
phrase or raw signature.

**Completed 2026-10-11:** the replacement merchant receiving wallet passed
this recovery and local-signature check. The protected runtime configuration
and an unpaid public quote were then verified against the replacement address.

## Bounded Base-mainnet acceptance

Before public sales, the three paid launch routes can be exercised through a
hidden acceptance handler. It stays on a separate Base-mainnet x402 middleware
while normal public routes remain on Base Sepolia. It accepts only the configured
independent buyer, once each for Instagram profile, Instagram post, and LinkedIn
profile; each payment must use native Base USDC at the catalog price. The handler
blocks B2B and service-credit bypasses, reserves provider capacity before
settlement, and retains the normal paid-result recovery path.

The owner runs the local buyer command only after the acceptance handler has
been enabled with the named buyer and all launch checks are green:

```bash
uv run python scripts/x402_mainnet_acceptance.py \
  --expected-buyer <independent-buyer-address> \
  --expected-pay-to <merchant-address> \
  --instagram-post-url <public-instagram-post-or-reel-url> \
  --confirm-mainnet-acceptance
```

The command reads the buyer phrase through hidden terminal input, validates the
exact challenge before signing, sends at most one payment per route, verifies
paid-result recovery, and polls LinkedIn with its protected job token. It does
not retry an uncertain paid request.

Before setting `X402_NETWORK=eip155:8453` and `ALLOW_MAINNET_X402=true`, rotate
the exposed CDP credential, run restore verification, check the credit balance,
complete an independent-buyer acceptance for each route, and record the
reconciliation. These actions are release holds, not conditions that software
can simulate.

### Completed independent acceptance — 2026-10-11

The named independent buyer completed the three one-time Base-mainnet routes:
Instagram profile and post at 50,000 native-USDC atomic units each, and
LinkedIn profile at 100,000. Each transfer settled to the configured merchant
address, had a matching durable receipt and one-time route reservation, and
recovered its paid result without a second transfer. The LinkedIn job completed
after one provider run whose reference was recorded before polling.

The two Instagram calls each consumed one ScrapeCreators credit at 1,880
micro-USD. LinkedIn completed with one recorded provider unit at 10,000
micro-USD, below its accepted 50,000 micro-USD cap. The root-owned, mode-0600
operations reconciliation record contains the transaction references, Base
blocks, receipt checks, and provider-consumption evidence. It contains no raw
payment signatures, job tokens, provider credentials, source URLs, or wallet
recovery material.

The normal public payment lane remains Base Sepolia and the separate acceptance
handler was disarmed after its routes were consumed. The emergency-pause drill
also passed: it returned HTTP 503 before a new payment challenge while an
already-paid result remained recoverable, then resumed with a healthy hosted
service. Manual refund and provider-outage rehearsals remain release holds.
