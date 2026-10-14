### Domain
reachsocial.dev

### Status
unclaimed — No accepted agent.json manifest yet, but it accepts 402 payments

### Payment protocol(s)
x402 (Base, native USDC), version 2

### How did you discover this API?
I own / built it (source = self)

### Your relationship to this domain
I own / operate this API. Submitted on the owner's behalf.

### Additional context
ReachSocial provides normalized public social profile, post, and feed data.
Eight public services cover Instagram, X, and TikTok at $0.05 USDC per request on Base mainnet.

- Website: https://reachsocial.dev
- API documentation: https://reachsocial.dev/docs/api
- Public executable services: https://reachsocial.dev/v1/services
- OpenAPI: https://reachsocial.dev/openapi.json
- Agent instructions: https://reachsocial.dev/agent.md

An unpaid POST to /v1/services/instagram.profile/execute with a fresh random 32–255-character Idempotency-Key and JSON body {"input":{"url":"https://www.instagram.com/instagram/"}} returns an x402 payment challenge when that service is ready. No payment or provider execution is needed to inspect the challenge. Paid result recovery uses the original key and input.

Please index as unclaimed pending a compatible agent.json manifest. No MPP or Lightning support is claimed.

### Checklist
- [x] This domain is not already in the registry (checked before submission).
- [x] This domain serves a real, publicly accessible API.
- [x] I am not submitting this to impersonate another service.
