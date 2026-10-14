# Developer onboarding audit — 2026-10-14

Scope: the homepage example, API documentation, browser helper, wallet
readiness panel, and their cross-origin interfaces. This is an update audit,
not a penetration test of the whole production estate.

## Findings and corrections

| Finding | Correction |
| --- | --- |
| Docs content expanded a 390px viewport to 601px. | Allow grid children to shrink and keep long code inside scrollable blocks. Checked 320, 390, 768, and 1440px widths. |
| CSS overrode the hidden network-switch button. | Enforce the native hidden attribute and distinguish disabled controls. |
| Usage code contained literal backslash-n text and omitted imports. | Render a typechecked quick-start file with imports, real newlines, and its own copy control. |
| The lost-response example depended on a return value that would not exist after failure. | Save the original key before payment; provide recovery after a reload and document uncertain outcomes. |
| Repeated copy clicks could permanently change button labels; the fallback could throw. | Preserve labels, serialize clipboard work, catch both failures, and open the source for manual copying. |
| Wallet announcements duplicated the legacy provider and reset selection. | Deduplicate provider objects and preserve selection. |
| Reconnects accumulated listeners; disconnects and late reads could display stale balances. | Clean up listeners, reset the panel, ignore stale reads, and add refresh/disconnect controls. |
| The panel could check a configured testnet token while claiming to read Base mainnet. | Pin readiness reads to native Base-USDC; use live metadata independently in the paid helper. |
| An account/network change after discovery was not checked at signing. | Recheck both at the signing boundary; allow only one signature attempt per payment client. |
| The helper accepted alternate transfer methods and unspecified signing-domain values. | Restrict to native-USDC EIP-3009 and its domain, supply EIP712Domain fields for injected wallets, and reject Permit2. |
| Fetch could follow redirects or attach same-origin cookies. | Pin the example to ReachSocial, reject redirects, and omit credentials on all requests. |
| CORS recovery disappeared when a paid service became private. | Allow key-bound sync recovery for retained catalog services without opening private execution or job polling. |
| Discovery cached without an Origin could omit CORS headers. | Public discovery includes the same wildcard policy regardless of Origin. |

## UI changes

The homepage leads to developer setup and shows a short profile excerpt, with
the complete stored response available without JavaScript. The animation ends
after 3.9 seconds and is disabled for reduced motion. The docs use numbered
setup steps, page navigation, neutral code colors, a response field guide, and
secondary wallet and troubleshooting sections.

## Verification

- Ruff and TypeScript checks pass.
- 185 Python tests pass; 17 credentialed provider tests remain skipped.
- 29 JavaScript tests pass, including concurrent quick-start clicks and the actual x402 fetch wrapper with a
  mocked wallet, facilitator response, and provider dispatch. One signature
  and one simulated dispatch are followed by uncharged recovery.
- Wallet tests cover absent/multiple wallets, rejection, wrong network,
  insufficient balance, unavailable balance, disconnect, and stale reads.
- Headless Chrome checks both pages at 320/390/768/1440px, actual clipboard
  copying, hidden controls, reduced motion, no-JavaScript example access, and
  absence of uncaught page errors.
- npm production dependency audit reports no known vulnerabilities.

No real payment, provider call, wallet secret, or new service promotion was
used for this audit.

## Outstanding acceptance

The owner-controlled browser-wallet mainnet acceptance remains open. A Python
wallet script cannot establish the injected browser-wallet/CORS signing flow.
Its payment cap also does not enforce a one-provider-credit cap: Instagram
profile currently permits a provider retry. Arrange a server-enforced
single-attempt acceptance before spending under the agreed one-credit limit,
then reconcile the actual transfer, provider attempt, and key-bound recovery.
Do not mark this live gate complete based on mocked tests.
