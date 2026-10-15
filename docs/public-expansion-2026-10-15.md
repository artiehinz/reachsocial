# Fifteen public APIs — 2026-10-15

The owner explicitly authorized skipping the 24-hour public-release waiting
period after reviewing the completed acceptance checks. This decision supersedes
the earlier inter-stage-only waiver. It does not claim a completed observation window.

Promoted: Instagram feed and saved highlights; YouTube channel, video and feed;
Facebook profile; Reddit post. All seven passed owner-approved USDC execution,
repeat recovery, transaction verification, and receipt/provider reconciliation.
See [Instagram evidence](stage-a-acceptance-2026-10-15.md) and
[combined evidence](combined-acceptance-2026-10-15.md).

The deployed Reddit fix passed a fresh one-credit provider check at
2026-10-15 21:41:06 UTC. Normalized author handle, account ID and profile URL
matched the provider author fields; post/gallery identifiers were not reused.
No raw response was retained, and no additional wallet payment was requested.
Provider balance: 6,771 → 6,770; reserve: 1,000; public capacity: 5,770.
Conservative provider ledger: 43 units. Remaining batch allowance: $0.05 and
10 provider credits; the $0.05 remains reserved for AgentCash.

All fifteen public services cost $0.05 per successful request. Feed bounds,
single-attempt public provider configuration, daily upstream cap, live credit
checks, service circuits, and stored-result recovery remain in force. Temporary
owner acceptance and canary lanes remain disabled. LinkedIn and current
Instagram stories remain on hold; Person News remains private.

Catalog flags drive website counts, pricing, OpenAPI, agent guides and MCP tools.
The homepage now names all six public platforms, and individual service examples
cover the newly available URL shapes. No owner-only OAuth access restriction
was lifted. AgentCash and Smithery compatibility remain open, distinct checks.

Deploy through GitHub CI, verify the exact running image, check health and
fifteen-service discovery, inspect unpaid $0.05 challenges for the seven new
public routes, and recover prior paid results without another execution.
Continue scheduled unpaid readiness checks after release.
