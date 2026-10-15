# Deployment and unpaid client acceptance — 2026-10-15

## Deployed operations release

[PR #22](https://github.com/artiehinz/reachsocial/pull/22) passed required CI and
merged through branch protection as `980fb047f7cfa1481d3d29109fbd184ba739155d`.
The [production deployment](https://github.com/artiehinz/reachsocial/actions/runs/38798120318)
succeeded, including the scoped InstaGet client provisioning. A direct Docker
inspection confirmed that exact running image tag and healthy status; public
`/healthz` returned `ok`. AEU remained healthy on its existing image.

The installed privileged operations package remains the separately approved
`a809ebd`. Application deployment does not replace root-owned operations scripts.

The readiness workflow is active at `17,47 * * * *`. Its
[post-deployment manual run](https://github.com/artiehinz/reachsocial/actions/runs/38798458078)
and [scheduled run](https://github.com/artiehinz/reachsocial/actions/runs/38798995423)
both passed. Monitoring checks public health and unpaid application discovery,
readiness, OAuth metadata, and the anonymous MCP challenge.

## Unpaid evidence

`tests/test_oauth_http.py` adds a fresh MCP SDK client using a real loopback HTTP
server, empty SQLite database, clean process environment, and an unfunded
in-memory test identity. It verifies:

- Dynamic client registration, SIWE login, PKCE, issuer/state binding, and CSRF.
- Rejection of a wrong verifier and reused authorization code.
- Actual SDK initialization, tool discovery, a single unpaid Instagram intent,
  and stable same-key retrieval from a fresh SDK session after token renewal.
- Invalidation of the old access token, browser connection revocation, and
  rejection of the revoked access/refresh tokens.
- Zero payment receipts and zero provider attempts in the isolated database.

The targeted OAuth/browser/HTTP suite passed all 28 tests. Ruff passed.

An isolated Chrome profile checked `/`, `/docs/api`, `/account`, and the unpaid
payment page at widths 320, 390, 768, and 1440: no horizontal viewport overflow
or uncaught JavaScript exceptions. Synthetic wallet checks covered two discovered
providers, no automatic connection/signature, a declined prompt, a simulated
pilot 403 before signing, real local SIWE through browser JavaScript, and account
change clearing both UI and server session. Keyboard Tab reached an interactive
control. These are synthetic-wallet checks, not MetaMask compatibility evidence.
Local reports/screenshots are under `data/unpaid-client-checks/` on Herald.

Live unpaid production checks passed:

| Surface | Result |
| --- | --- |
| Health, readiness, status, executable services, OpenAPI, OAuth metadata | 200 |
| Anonymous MCP initialization | 401 with resource metadata challenge |
| Non-owner login challenge | 403 |
| Instagram profile without payment, with random key and browser Origin | 402, Base native-USDC, exactly 50,000 atomic units, expected receiver, public CORS |
| Explicit recovery with that unpaid key | 404 with public CORS; no paid execution |

The expected receiver is `0x76bCc44696A4c67579A6aF2F25CF953BE0931E38`.
Public checks used an explicit diagnostic User-Agent and JSON Accept header.

The live balance read returned 6,779 provider credits. The protected reserve is
1,000, the daily upstream ceiling is 5,000,000 micro-USD, provider attempts are
limited to one, and owner-only OAuth access remains enabled. Production had
12 settled receipts, two canceled-before-settlement receipts, and 99 aggregate
provider attempts. These are an observation baseline, not attribution of all
traffic to this acceptance batch. No payment was signed during these checks.

## Standalone Firefox/MetaMask acceptance passed

On 2026-10-15 at 20:21 UTC, the owner approved the prepared standalone browser
test in the existing Firefox/MetaMask session on Herald. Production was running
`348d126dd6b97233a2005fe413c0f7f57832c35d`; its CI, deployment, and final readiness
run passed. The cross-origin page reported `paid result recovered twice`.

- Service: `instagram.profile`; amount: 50,000 native Base-USDC atomic units.
- Transaction: `0x18cefe2ada1f1785ba5030ac64bed99de1bba22cfc6f4486151d78074c2c2052`.
- Request: `req_a4f972f82de94ce0aa3762f332b9fcaa`.
- Independent Base RPC check: successful receipt in block 52,653,185; exactly
  one matching native-USDC transfer from the approved owner to the receiver.
- Production: one settled five-cent receipt and one successful provider attempt,
  consuming one credit. Live balance decreased from 6,779 to 6,778.
- Two additional independent recovery-only requests matched the browser's result
  hash `16ba381b6840f52ef39cb4bee82c23d1b35648e56d75a8729fd3aef35bf6be1f`.
  Neither recovery signed a payment or dispatched a provider execution.

The original request key remains in the Firefox checkpoint and protected local
evidence. Do not clear it or repeat the paid browser case. Production totals
after payment were 13 settled receipts, two canceled-before-settlement receipts,
and 100 provider attempts. This closes standalone browser acceptance; it does
not establish AgentCash, Smithery, or staged-service acceptance.

## Remaining owner acceptance

After the Firefox payment, eight allocations remain: AgentCash and seven staged
services, each capped at $0.05. The batch remainder is **$0.40 and 18 provider
credits**, further bounded by the original release allowance.

### Historical preparation before the Firefox test

The remaining allocations are one standalone browser request and one AgentCash
request, each capped at $0.05. Refresh the balance and receipt baseline before
signing; count each against the remaining $0.45/19-credit release allowance.
Keep the existing successful direct-MCP checkpoint and do not replay that paid
case as a substitute for either of these independent client checks.

The portable browser harness is prepared locally at
`data/browser-acceptance.zip`. Extract it on the computer with the funded owner
MetaMask extension, then run:

```bash
python3 -m http.server 8766 --bind 127.0.0.1 --directory /path/to/browser-acceptance
```

Open `http://127.0.0.1:8766`. The page uses the existing bundled browser client
against production from a separate origin, pins the owner/receiver and five-cent
limit, and saves its random key before requesting payment. It permits one
attempt; reloads or interruptions leave only recovery enabled. Recovery runs
twice without a wallet and checks settled state plus matching result hashes.
Keep the same browser profile/port and original key. Local simulated success and
lost-response checks passed; no real wallet payment has been made with it.

AgentCash is not installed on Herald. Version `0.17.1` was downloaded for source
inspection only. Even its unpaid `check` command initializes/loads AgentCash's
own local wallet; its payment path does not use the MetaMask browser extension.
The owner must identify the existing funded AgentCash installation before the
paid case. Do not import browser-wallet secrets into this workflow. See
[AgentCash wallet documentation](https://agentcash.dev/docs/wallet/overview).

On that owner computer, save a separate random 32–255 character key before any
call. Use it for the check, one paid request, and recovery; never replace it to
retry an uncertain charge. The reviewed CLI supports the following bounded
command after owner approval (the value of `reachsocial_request_key` must come
from the saved checkpoint):

```bash
npx agentcash@0.17.1 fetch \
  https://reachsocial.dev/v1/services/instagram.profile/execute \
  --method POST \
  --body '{"input":{"url":"https://www.instagram.com/instagram/"}}' \
  --header "Idempotency-Key: $reachsocial_request_key" \
  --payment-protocol x402 --payment-network base --max-amount 0.05 --yes=false
```

First use `agentcash@0.17.1 check` with the same endpoint, body, and header to
confirm the schema and price without paying. After the single paid attempt,
use ordinary HTTP POST to `/v1/payments/recover/instagram.profile` twice with
the original header/body, without AgentCash or a payment signature. Preserve
the transaction reference and result hashes for independent transfer/provider
reconciliation. CLI behavior and flags were checked against the
[official CLI reference](https://agentcash.dev/docs/cli/fetch) and published package.

## Gates still open

- AgentCash payment/recovery acceptance.
- Fresh external production-client authorization and metadata interoperability,
  including Smithery. A local SDK test does not prove these integrations.
- Remaining staged-service payments/observation and directory publication.

Owner-only access remains enabled. These checks do not authorize new public
services or removal of the pilot restriction.
