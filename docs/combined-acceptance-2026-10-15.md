# Combined five-service acceptance — 2026-10-15

The owner authorized running the five later checks together without the planned
inter-stage wait. All five paid executions and repeated recovery passed; this
does not close observation, external-client compatibility, or data-quality gates.

| Service | Settled UTC | Base block | Execution request |
| --- | --- | --- | --- |
| `youtube.channel` | 2026-10-15T21:09:47Z | 52654622 | `req_f8dd1ad49b6f48d0a0ed03e68f67d37e` |
| `youtube.video` | 2026-10-15T21:10:49Z | 52654653 | `req_fd302224c0dc462a9fadfd1ebb0981c1` |
| `youtube.feed` | 2026-10-15T21:13:57Z | 52654750 | `req_8b54d2b2715d401e8e021270720149f5` |
| `facebook.profile` | 2026-10-15T21:19:20Z | 52654909 | `req_7292ea3688f44b15b10084074e2e462b` |
| `reddit.post` | 2026-10-15T21:20:30Z | 52654944 | `req_9b20f01bb3dc4a66bcd7cdf29b3f41ea` |

Each transaction was independently verified on Base: exactly one 50,000-atomic
native USDC transfer from the approved owner to the merchant. Each execution
used one successful provider attempt and one credit. Total: **$0.25, five credits**.
Balance: **6,776 → 6,771**, preserving the 1,000-credit reserve. Database totals:
20 settled receipts, two canceled-before-settlement receipts, 107 provider attempts.

The runner retrieved each saved result twice. After disabling the acceptance
lane and restarting the app, two independent recovery-only calls per original
request matched its saved hash; all five new acceptance routes returned 404.
Production image remains `787ab043a4fb8fd4aa483c842ccbdf3b8de8cd23`.
Run: `combined-8df7ac7e53d82bfd9c7ec0a6`. No public services were promoted.

## Data-quality blocker

The Reddit result assigns `gallery` as author handle, the post ID as author ID,
and the gallery URL as author URL. The shared normalizer currently passes the
whole Reddit post into profile/author normalization. This is incorrect attribution,
despite schema completeness and successful payment/recovery. Keep Reddit private
until author mapping is corrected and verified. No additional payment was made.

The release-preparation change now maps the provider’s `author` and
`author_fullname` fields explicitly, with regression coverage for gallery posts,
deleted/missing authors, and malformed author values. The provider contract is
[documented here](https://docs.scrapecreators.com/v1/reddit/post/). This fix has
not yet been verified against a fresh live result. Existing paid results stay
unchanged so recovery continues to return the original saved result.

## Evidence

- `facebook.profile` transaction: `0x768c57ecf8742bb6b26487a5d2484d6b6b2f7b013d6f924bc973f059ece15144`;
  result SHA-256: `d7b127fb6734823285ab660ae993c44be361057e24e335172dbe28a15e843542`.
- `reddit.post` transaction: `0x8a63e79b3563c6ebea8946f4622dcabd815ddb691f60e7a7c99ebae2d9f9a2d7`;
  result SHA-256: `de4a49a982ee1eae1ce96b4ec337ef7de733b61e0fdd88918e2ed4f865e3af50`.
- `youtube.channel` transaction: `0x7c78f0eff8541df99a42f66ae08b842303103f88d461a2d86b4a6b1bb6d60c16`;
  result SHA-256: `b39adf605ecee55129133db86854cf7990c836c7126756b820d1bbdec9c4657b`.
- `youtube.feed` transaction: `0x9c2f9e6af5aa0ab85a609d0c357171ac9f26060a44165244e2dd55724f2765ef`;
  result SHA-256: `6006b8801ebbf61a252c5b30ed18dee2101a8abf2803a5ea1f17a89f8e7a962d`.
- `youtube.video` transaction: `0x664f744651057fae33ddec97611e7eef28032900be4f31d91f338d959db85b6b`;
  result SHA-256: `d16f678199a20148af23d22c8f3351108bd0cdcc0ba80be63ee006e347cfd827`.

Original checkpoints and structured audit stay in ignored mode-0600 files on
Herald; no provider payloads or payment signatures are retained in this evidence.

## Remaining gates

Remaining batch allowance: **$0.05 and 11 provider credits**, with the $0.05
reserved for AgentCash. The conservative original provider ledger totals 42 units.
AgentCash and Smithery checks remain open. Public-release observation remains
open; the immediate combined run does not establish a clean 24-hour window.
Post-batch unpaid readiness: [run 38809316276](https://github.com/artiehinz/reachsocial/actions/runs/38809316276).

The post-batch readiness workflow passed; `/healthz` and `/readyz` returned
200 with `ok` and `ready`. Observation baseline: 2026-10-15 21:25 UTC; a
24-hour review is no earlier than 2026-10-16 21:25 UTC and still requires
monitoring evidence and reconciliation.
