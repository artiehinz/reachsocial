# Provider contract status

Last verified: 2026-08-09. This file contains no credentials or raw provider payloads.

## InstaGet internal consumer contract

The envelope now carries `meta.schema_version`,
`meta.normalization_version`, and `meta.response_shape`. InstaGet validates and
narrows that normalized data before persistence; it does not receive provider
keys, raw payloads, or provider logs. This is only a fixture-level integration
gate. It does not mark a service as cost-verified or accepted for live traffic.

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

The replacement production token authenticates successfully. Bounded validation
has established this baseline:

- `x.feed` — `apidojo~tweet-scraper` completed runs `jr21WOWnGJCvUnWxp` and
  `QcMkEHzsIAz1DhJAu`; each reported a stable cost of 2,000 micro-USD. The
  current validation dataset contained five `noResults` sentinels rather than
  tweet records, so the billing gate passed but the provider contract failed.
  The service remains disabled and is not public.
- The former `linkedin.profile` Actor was rejected before charging because it
  requested full Apify-account permission. Its replacement,
  `automation-lab~linkedin-profile-scraper`, completed run
  `RKYppR10hFPM21RV0` under the $0.05 cap, returned one valid normalized profile
  with current employment data, and reported a stable cost of 18,000 micro-USD.
  At a $0.10 public price, the $0.05 hard cap preserves a worst-case 50% gross
  margin. The service is accepted for Base Sepolia publication.
- `instagram.stories` has no active Actor. The former Actor's $19/month rental
  is not accepted for this cycle.

Apify execution requires a server-side total-charge cap, a bounded dataset item
count, and a 120-second Actor timeout. Run IDs are persisted immediately so
worker recovery polls the accepted run rather than creating another paid run.
Apify services do not use automatic run retries, and stable costs are read after
the provider's post-completion accounting delay.

Instagram Stories remains disabled while the no-login, pay-per-result
alternatives remain candidates for a later separately approved bake-off:

1. [`data-slayer~instagram-stories-scraper`](https://apify.com/data-slayer/instagram-stories-scraper)
   is the primary candidate: no Instagram login and advertised per-result
   pricing, with more observed usage than the other low-cost candidate.
2. [`intropix~instagram-stories-scraper`](https://apify.com/intropix/instagram-stories-scraper)
   is the secondary candidate: no login and explicit start/profile/story event
   prices, but it is substantially newer and less proven.

Neither candidate is configured, called, or exposed during this cycle.
