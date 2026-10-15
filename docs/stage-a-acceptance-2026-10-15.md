# Stage A Instagram acceptance — 2026-10-15

Paid acceptance and recovery passed for `instagram.feed` and
`instagram.highlight` in the owner's Firefox/MetaMask session. Both remain
private. AgentCash and Smithery compatibility remain open.

| Service | Settled at (UTC) | Base block | Verified result |
| --- | --- | --- | --- |
| `instagram.feed` | 20:57:31 | 52,654,263 | Five normalized items; one attempt/credit; matching recovery |
| `instagram.highlight` | 21:00:05 | 52,654,334 | Five normalized items; one attempt/credit; matching recovery |

Each payment transferred exactly 50,000 atomic native Base-USDC units ($0.05)
from the approved owner to the merchant. Independent Base RPC checks confirmed
successful receipts and exactly one matching transfer per transaction:

- Feed: `0xc1b9f308d8b711190a24498f946251774cc5f6d990be71e999a09a534d892478`.
- Highlight: `0xf2227b7cbf4b78d9efb4573c74c3782d26f781793cf95733505bf9cd07f338fc`.

Execution requests: `req_3d2fdcf422534f53bc6aa6e61fe10c10` (feed) and
`req_ca16e9592e314cda93190b3e4eebf7a9` (highlight). Original OAuth/MCP checkpoints
remain in ignored mode-0600 files on Herald. Evidence retains no wallet secrets,
signatures, media, or provider responses.

Two independent recovery-only calls per request matched these result hashes:

- Feed: `6e94c7101da1ff23e5952fd5b5252817050f5d319f7e570b162f85d14ea799ee`.
- Highlight: `fb944fab38db893ad99a4dfb272effdda4cfd0f5a1930cdf842609399aa36fa0`.

The highlight used the previously passing
[provider-documented sample](https://docs.scrapecreators.com/v1/instagram/user/highlight/detail/).
Both requests limited output to five items; no further pagination was executed.
Provider balance decreased from 6,778 to 6,777 to 6,776, preserving the 1,000-credit
reserve. Production totals were 15 settled receipts, two canceled-before-settlement
receipts, and 102 provider attempts. The conservative local provider ledger now
records 37 units against its original 100-unit cap.

## Browser repairs

The first feed approval stopped before wallet signing: the server supplied a
relative endpoint, but the browser expected an absolute URL. Its five-minute
approval window remained active without a signed attempt or receipt. The
original request/key were retained through repair and successful payment.

[PR #24](https://github.com/artiehinz/reachsocial/pull/24) normalizes the endpoint
against the fixed production origin while retaining exact host/service/path
validation. [PR #25](https://github.com/artiehinz/reachsocial/pull/25) versions the
payment module and helper import after Cloudflare served the stale unversioned
helper. All 42 frontend tests and required CI/deployment checks passed.

Production image: `787ab043a4fb8fd4aa483c842ccbdf3b8de8cd23`. The live HTML,
versioned entry module, and helper checksum were checked before payment resumed.
Helper SHA-256: `aa8a0fd1200c31e1e3e6255a3561eeb664f14d6426111862f7a88ae8e0e68525`.

## Closed lane and observation gate

Run ID: `stage-a-c1ba435161d184a478e35e8d`.
`MAINNET_PRIVATE_ACCEPTANCE_ENABLED=false` was restored after both tests.
Post-restart checks at 21:02 UTC confirmed health/readiness, eight public services,
404 from both disabled acceptance routes, and successful paid recovery for both
original requests. No public service was promoted.

Observation baseline: **2026-10-15 21:03 UTC**. Do not advance to Stage B or
complete this gate before **2026-10-16 21:03 UTC** (15:03 America/Denver), and only
after reviewing monitoring, receipt/provider reconciliation, and credit capacity.
Scheduled unpaid readiness checks remain enabled; elapsed time alone does not
establish a clean observation window.

Remaining budget: **$0.30 and 16 provider credits** for AgentCash and the five
later services (YouTube channel/video/feed, Facebook profile, Reddit post),
further bounded by the original release allowance. External-client compatibility
remains a separate gate.
