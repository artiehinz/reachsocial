# Provider contract status

Last verified: 2026-08-25. This file contains no credentials or raw provider payloads.

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

### InstaGet Herald acceptance

ReachSocial commit `50d5284fddb3f04527b3566a3950b5622cb68ece` is running
on Herald as image digest
`sha256:8b3a284399a750014a20651bfb50a9091a7f52197360fbd58ca5b2c1d5455ed0`.
The active internal `InstaGet-Herald` client is entitled only to
`instagram.profile`, `instagram.post`, and its pre-existing `news.person`
integration.

Bounded uncached Instagram shadows passed with schema `1.0`, normalization
`v1`, and one charged provider unit each:

- profile request `req_12164987baa94854a9ee99f7dc49c720`;
- post request `req_565a3401f752480a9c4bcbe89edba4ce`; and
- guarded InstaGet worker request `req_e098ea9fdb0b4aa9b9b94f629c2fa0d8`.

The full diagnosis and acceptance cycle used six provider credits: two final
shadows, one guarded worker call, one structure-only diagnostic, and two
post attempts that reached the provider while exposing and then confirming
the normalization/idempotency fixes. A client rate-limit rejection occurred
before the provider boundary and cost zero. Starting from the owner's stated
88-credit free balance, the estimated remainder is 82 credits. This estimate
is test-capacity evidence only; no paid pack has been purchased or reconciled,
so `cost_verified` remains false.

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
