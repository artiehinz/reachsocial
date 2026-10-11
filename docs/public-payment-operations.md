# Public payment operations

This runbook covers staged Base-USDC release work. Instagram profile and post
are the only currently available public services, at $0.05 each on Base
Sepolia. LinkedIn remains $0.10 per job in validation while its ScrapeCreators
replacement returns `not_found`; it is not available for public payment. This
runbook does not authorize another provider credit purchase, catalog expansion,
or an AEU payment mode.

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

Set `SCRAPECREATORS_CREDIT_BALANCE` to the returned balance as the startup
baseline and retain `SCRAPECREATORS_CREDIT_RESERVE=1000` for InstaGet. Before
each public-mainnet ScrapeCreators settlement, the application reads the live,
account-wide provider balance, subtracts that reserve and active public holds,
and aborts before settlement when the check fails or capacity is exhausted.
Completed public and private calls are already reflected in the live balance
and are not subtracted twice. No code path tops up automatically. The existing
$5 daily upstream-cost cap, public request limits, and provider concurrency
limit remain in force.

The 2026-10-11 release baseline was 6,825 credits. The bounded provider run
ended at 6,812, with the 1,000-credit internal reserve intact. Its local ledger
uses a 100-credit ceiling and conservatively records every uncertain
ScrapeCreators attempt; it never keeps raw source URLs or provider payloads.
This is a balance observation, not an invoice or an authorization to buy
credits. Recheck it immediately before enabling mainnet so later InstaGet use
is accounted for.

LinkedIn has moved from Apify to ScrapeCreators. The new public-profile endpoint
is priced from the same 1,880 micro-USD one-credit replacement basis, but three
fresh samples returned `not_found`. It remains disabled until a successful
provider contract and a new paid submission, polling, and recovery acceptance
pass. Before the provider call, the worker writes a durable dispatch marker. A
restart after dispatch but before result persistence becomes
`reconciliation_required`; it never blindly repeats an uncertain upstream
request. Provider timeout, unavailability, or internal failure makes exactly
one replacement service credit claimable by an eligible job holder.

## Paid-result recovery

New anonymous paid calls must include a random 32–255 character
`Idempotency-Key`; a UUIDv4 is acceptable. Reuse it only with the same service
and input. If the client loses the response, it may
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

Critical payment, provider, capacity, job, memory, or disk alerts also latch a
runtime payment pause and make `/readyz` return 503. DigitalOcean checks that
endpoint from three regions and emails the verified account after a two-minute
global outage; a separate policy warns 14 days before TLS expiry. Fix the cause
and recreate only the app container with the current image to clear the latch.

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

The historical three-route acceptance handler is disarmed and its one-time
routes are already consumed. It does not validate the ScrapeCreators LinkedIn
migration. Do not re-arm or reuse it. A fresh LinkedIn acceptance is required
only after its provider contract succeeds; it must use a newly reviewed,
single-use acceptance path or the normal public route after mainnet is enabled.

Before the earlier public-sales decision, the three paid launch routes could be exercised through a
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
service. An isolated provider-outage rehearsal also passed: a paid async
failure persisted its provider reference, granted exactly one replacement
credit, and resumed an existing provider run rather than starting another.

The off-host recovery path was verified with the configured DigitalOcean
credentials: a temporary volume was created from the newest `tor1` production
snapshot and then deleted without attaching it or touching production. The
remaining release rehearsal is a merchant-signed refund. Run it locally, never
over SSH or on the Droplet:

```bash
uv run python scripts/mainnet_refund_rehearsal.py \
  --expected-merchant <X402_PAY_TO-address> \
  --expected-buyer <independent-buyer-address> \
  --confirm-refund
```

The command sends exactly 50,000 native Base-USDC atomic units by default,
requires a hidden local recovery-phrase entry, confirms the Base chain and
recipient, and verifies the resulting ERC-20 transfer. Without
`--confirm-refund`, it is a dry run. It does not write wallet material, signed
transactions, or payment signatures to disk.

**Completed 2026-10-11:** the merchant returned 50,000 native Base-USDC atomic
units to the independent buyer. The transaction and exact ERC-20 transfer log
were reconciled in the protected operations record. The first local command
reported a receipt-validation failure after the broadcast because Web3 returned
the log fields as bytes; the transfer itself was successful. The verifier now
normalizes those fields, has regression coverage, and must not be used to send
a second refund for this rehearsal.
