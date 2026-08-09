# Provider contract status

Last verified: 2026-08-08. This file contains no credentials or raw provider payloads.

## ScrapeCreators

Credentialed live samples passed for:

- `instagram.profile`
- `instagram.post`
- `x.profile`
- `x.post`
- `tiktok.profile`
- `tiktok.feed` with `max_cursor` pagination
- `tiktok.video`

Each successful sample reported one charged credit and returned the expected
provider-neutral ReachSocial shape. The provisional catalog cost is 1,880
micro-USD per credit. `cost_verified` remains false until the owner confirms the
actual purchased pack price. The existing Instagram endpoints retain their
current Base Sepolia availability. The newly implemented X and TikTok endpoints
remain `enabled: false` and `public: false` until this release gate is cleared.

The first stale Instagram post fixture returned `not_found`; a current public
post then passed. This confirms non-retryable content errors are translated
without a fallback provider call.

## Apify

Implemented adapters:

- `instagram.stories` — `louisdeconinck~instagram-stories-scraper`
- `x.feed` — `apidojo~tweet-scraper`
- `linkedin.profile` — `dev_fusion~linkedin-profile-scraper`

All three start requests were rejected before a run was created. Apify returned
HTTP 403, error type `platform-feature-disabled`, with the sanitized reason
“Too many outstanding invoices.” Because no successful runs or actual-cost
samples exist, these services remain `enabled: false` and `public: false`.

After Apify billing is resolved, rerun each service with
`scripts/provider_contract_smoke.py`, record the completed run charge, validate
representative normalized fields, set a fixed margin-safe price, and only then
enable its catalog flags.
