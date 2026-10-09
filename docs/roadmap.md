# ReachSocial roadmap

## Base mainnet USDC launch gate

**Status (2026-10-08):** ReachSocial is live with authenticated B2B access,
MCP discovery, and anonymous x402 challenges on Base Sepolia. Base mainnet is
intentionally blocked.

Do not set `X402_NETWORK=eip155:8453` or `ALLOW_MAINNET_X402=true` until every
item below is complete and recorded in the release notes.

1. **Verify the provider cost.** Reconcile the purchased ScrapeCreators pack or
   invoice with the current catalog cost for `instagram.profile` and
   `instagram.post`, then mark only those reviewed costs as verified. See
   [provider contract status](provider-contract-status.md).
2. **Rotate the CDP credential.** The current credential was exposed during an
   earlier operational review. Replace it in CDP and in the runtime environment
   before any mainnet use.
3. **Establish wallet recovery.** Create or recover the dedicated receiving
   wallet, record the wallet secret in the owner's password manager, and verify
   that recovery works without relying on the server. Do not store the secret in
   the repository or publish it in deployment output.
4. **Run one capped real purchase.** Use an independently funded Base-mainnet
   buyer wallet for one small request. Confirm the exact x402 requirement,
   facilitator settlement, service result, receipt, and provider charge.
5. **Reconcile and rehearse operations.** Match the buyer payment, ReachSocial
   receipt, provider cost, and accounting record. Exercise the payment pause,
   provider-outage credit, and refund/support paths before opening the route to
   more callers.
6. **Make the release decision.** Review the evidence, set the mainnet network
   and explicit allow flag, deploy, and verify the live 402 challenge with a
   fresh buyer. Keep a capped spend limit for the first production window.

The application refuses a Base-mainnet configuration unless the allow flag is
set and every public service has a positive verified upstream cost. That guard
is necessary but does not replace the operational checks above.
