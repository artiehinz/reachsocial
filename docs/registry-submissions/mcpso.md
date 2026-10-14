Name: ReachSocial
Type: Hosted remote MCP server
Website: https://reachsocial.dev
MCP endpoint: https://reachsocial.dev/mcp/
Transport: Streamable HTTP
Authentication: Authorization: Bearer <REACHSOCIAL_API_KEY>. Approved client access is required, including for tool discovery.
Access requests: https://reachsocial.dev/contact
Documentation: https://reachsocial.dev/docs/api
Server metadata: https://reachsocial.dev/mcp.json
Logo: https://reachsocial.dev/static/reachsocial-logo.svg

ReachSocial provides normalized public social profile, post, and feed data for applications and AI agents. Its authenticated MCP server exposes tools according to each client's service permissions.

Separately, eight public REST services for Instagram, X, and TikTok accept x402 payments of $0.05 USDC per request on Base mainnet. This public wallet-payment flow is REST access, not anonymous paid MCP access. Public availability is listed at https://reachsocial.dev/v1/services.

Categories: Social media, Data extraction, Developer tools.
The implementation repository is private; this submission is for the hosted remote service.
