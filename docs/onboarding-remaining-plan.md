# ReachSocial: remaining work after owner MCP acceptance

Updated 2026-10-15. The owner completed the real OAuth → MCP request → browser
payment → recovery flow. One $0.05 native Base-USDC transfer and one provider
credit were independently reconciled. See [release evidence](self-service-release.md).
This proves that flow for the owner; it is not general client or catalog acceptance.

## 1. Make the existing flow understandable

Implemented in this update:

- Explain actual access errors: pilot restrictions, wrong origin, expired session,
  expired authorization link, request throttling, and unavailable service.
- Show the account shared for login. Explain the difference between the wallet's
  selected account, site permissions, readiness-panel disconnect, and sign-out.
- Put login, agent consent, and past requests in separate sections, with one main
  action at each step. Preserve keyboard labels and live status announcements.
- Replace the payment page's raw JSON summary with service, target, price,
  network, and receiving wallet. Keep JSON for the actual result.
- Explain pending, successful, failed, expired, and reconciliation states. Keep
  refresh available without authorizing another payment. Hide the request ID
  under a reference disclosure, without hiding the receiving wallet.
- Use the same versioned wallet module in the header and account/payment pages,
  avoiding duplicate initialization through different module URLs.

Next usability checks, without paid calls:

- Desktop and narrow-screen review; keyboard focus, long addresses/URLs, and
  long result scrolling. Test multiple injected wallets and account changes.
- Confirm the account page reports a declined wallet prompt and a 403 accurately.
- Consider an explicit “Choose another account” action using wallet permissions
  only after testing supported extensions. Do not silently revoke permissions or
  request signatures when opening the readiness panel.
- Show friendly agent names alongside stable client IDs, and separate the
  requesting app and callback address in consent. Keep consent explicit.
- Add a copy-result action if users need it; avoid adding a general playground,
  animations, dashboards, charts, or new onboarding steps to this release.

The current implementation also invalidates the local sign-in/payment state
when an injected wallet emits an account or chain change. It signs out the
server session where possible and requires a new login before another signature
or payment approval. Consent now separates the requesting application, stable
client ID, permission, and callback address. The narrow mobile layout converts
request facts to one readable column; long addresses, URLs, and JSON results
wrap or scroll inside their panels.

## 2. Close self-service release checks

The [2026-10-15 unpaid audit](unpaid-client-acceptance-2026-10-15.md) passed fresh
SDK checks over real loopback HTTP, synthetic browser checks, live discovery/CORS
checks, and a scheduled readiness run. External production-client authorization
and the two owner-wallet payment cases below remain open.

- Run the separate standalone injected-browser acceptance and AgentCash path.
  Preserve idempotency, require owner wallet approval, and verify recovery.
- Test a real fresh MCP client, including client metadata/registration, PKCE,
  token renewal, connection revocation, payment link, and result retrieval.
- Unpaid monitoring now probes discovery, readiness, OAuth metadata, and the
  unauthenticated MCP challenge on a schedule. The application also records
  non-identifying authentication-failure signals, surfaces stalled signed MCP
  intents and stale backup markers, and separates informational auth/backup
  alerts from payment safety pauses. Confirm the workflow is enabled after the
  deployment.
- Unpaid intents become expired after 30 minutes but retain their hashed
  idempotency history for 30 days. Maintenance deletes expired state only after
  the recovery window and keeps signed/uncertain requests for reconciliation.
  Rotating refresh-token hashes remain through their family lifetime. Privacy
  wording now describes wallet addresses, sessions, agents, inputs, retention,
  and public transaction references.
- Root-protected nightly-backup restore passed on 2026-10-15 through the scoped
  operations wrapper, including OAuth/request tables and both databases. See
  [operations evidence](operations.md#evidence-and-remaining-acceptance); preserve
  the earlier isolated pre-deployment restore and historical receipt evidence.
- Remove owner-only restrictions only after the above gates pass. Verify public
  REST and existing B2B access independently; OAuth outages must not disable them.

## 3. Release the seven remaining social services

Promote only services that pass their own acceptance:

1. Instagram feed and saved highlights.
2. YouTube channel, video, and feed.
3. Facebook profile and Reddit post.

For each stage, confirm costs and credit capacity, run one bounded paid request
and recovery per service, verify the deployed catalog, then observe/reconcile for
24 hours before advancing. Keep failed services private. Maintain one-page feed
bounds and truthful pagination/data limitations. LinkedIn, public Person News,
and current Instagram stories remain on hold. AEU is unchanged.

The current batch has $0.45 USDC and 19 provider credits remaining, further
limited by the original $2 / 100-credit allowance. Do not double-count the owner
MCP flow as a second browser purchase. Count charged failures and retries. Keep
the 1,000-credit reserve, $5/day upstream ceiling, current request limits, and
single-provider-attempt acceptance setting. No automatic purchases or top-ups.

## 4. Publish working access and track external outcomes

- Keep website, OpenAPI, agent instructions, static cards, and MCP discovery in
  agreement with the deployed services, pricing, network, and access state.
- Publish the Official MCP Registry entry after HTTP domain verification and
  working fresh-client acceptance; protect the publisher key outside runtime.
- Retry Smithery after real OAuth acceptance. Follow up existing Glama, MCP
  Market, MCPservers.org, MCP.so, Open 402, and APIs.guru submissions without
  duplicates. Use artemhinz2@gmail.com as the approved public contact.
- Complete AgentCash/x402scan registration and indexing, and implement/verify
  the Bazaar discovery extension. Record submitted, approved, and indexed
  separately. See [directory tracker](registry-submissions/README.md).
- Keep the client documentation repository private until retained backend
  history cleanup is verified. Never publish application source or ops records.

## Completion

A fresh user can authorize a supported MCP client and recover a paid result
without owner intervention; the direct REST path remains keyless. All 15 selected
services have paid acceptance and observation evidence. Documentation, costs,
monitoring, restore evidence, and actual directory status agree. Until then,
report individual completed gates instead of declaring the entire release done.
