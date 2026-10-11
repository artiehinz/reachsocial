# Provider contract status

Last verified: 2026-10-11. This file contains no credentials or raw provider payloads.

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
provider-neutral ReachSocial shape. The catalog cost for the two public
Instagram routes is verified on a documented replacement-price basis of 1,880
micro-USD per credit ($47 / 25,000 credits), plus the endpoint consumption
evidence. This is not a purchased invoice. A later acquisition must be recorded
separately with its actual expense rather than relabeling this evidence.

The protected account balance check on 2026-10-11 returned 6,827 credits. The
mainnet application configuration reserves 1,000 credits for InstaGet before
new public work can be accepted, and holds the maximum retry units before a
payment reaches the provider. No automatic top-up exists. The existing Instagram
endpoints remain on Base Sepolia until the independent public-launch holds are
complete. The X and TikTok endpoints remain `enabled: false` and `public: false`.

### Bounded product-discovery batch — 2026-08-25

The refreshed ScrapeCreators OpenAPI inventory contains 184 review candidates.
That inventory is not a product backlog or publication approval. The bounded
batch used the product-relevant routes only and stored sanitized route/shape
evidence in `docs/generated/`; it never stored raw provider payloads,
identifiers, media URLs, or credentials.

- 14 one-credit calls succeeded for Instagram profile/profile-posts/search; X
  profile/post/user-tweets; TikTok profile/video/feed/user-search; and YouTube
  channel/video/channel-videos/search.
- A four-credit NASA Instagram grid pass also succeeded for the image,
  carousel, and reel detail variants. A prior three-credit Instagram pass
  confirmed carousel and reel, but did not expose an image in its first grid.
- The bounded cycle therefore used 21 provider credits. Based on the prior
  estimated 82-credit remainder, the estimated remaining free balance is 61;
  reconcile this with the provider account before buying a pack.

No new route is accepted, enabled, public, or entitled to InstaGet as a result
of this discovery evidence. Each still requires a reviewed ReachSocial service
definition, normalizer, sanitized consumer fixture, cost verification, and a
separate release decision.

### UI-fixture capture follow-up — 2026-08-25

A second controlled capture produced compact, sanitized presentation fixtures
for the offline InstaGet UI lab. The base capture repeated the 14-route batch
plus Instagram image/carousel/reel variants (18 credits). A three-call follow-up
captured the wrapper shapes needed for the X post/feed and YouTube video-search
cards (3 credits). The two JSON files retain only short public presentation
text, display fields, counts, and media-presence flags; they exclude raw
provider envelopes, provider IDs, source/media URLs, request IDs, and
credentials.

The additional cycle used 21 credits. The complete recorded discovery and UI
fixture work is therefore 42 credits against the earlier estimated 82-credit
remainder, leaving an estimated 40 credits; reconcile the actual balance in
the provider account before additional paid testing.

### Local media capture follow-up — 2026-08-25

The local admin UI lab was refreshed with bounded media files rather than
provider URLs. The 18-route capture charged 17 credits (the carousel route
returned `not_found` without a charge); a TikTok/browser-format retry and two
carousel retries used five more credits. The final carousel capture includes
six locally stored slides, and the lab serves all captured assets only through
its browser-admin route with `no-store` caching. These temporary files are not
committed or deployed as public static assets.

The recorded provider-testing total is now 64 credits, leaving an estimated
18 credits from the earlier 82-credit remainder. Confirm the account balance
before any further live calls.

The first stale Instagram post fixture returned `not_found`; a current public
post then passed. This confirms non-retryable content errors are translated
without a fallback provider call.

### Targeted UI-capture completion — 2026-08-25

After the provider allowance was replenished, a controlled follow-up completed
the previously incomplete admin-lab examples. Seven requests used 16 provider
credits: the Instagram profile, broad username search, Nike Football profile,
and corrected X post each used one; permanent TikTok media used ten; and the
Nike Football search was retried once after its capture alias was corrected.

- The Instagram profile capture now contains an avatar plus profile, follower,
  and following totals.
- `nikefootball` search leads to a separately captured Nike Football profile,
  including its avatar, biography, and profile totals.
- The X post now matches the requested Austen URL, rather than the previous
  unrelated provider result.
- The TikTok response supplies a saved local MP4, a same-item saved poster,
  author handle, and available likes, views, and comments.

Only sanitized presentation fields and local media filenames were retained.
Raw provider payloads, URLs, IDs, and credentials remain excluded. This is
offline UI evidence only; it does not accept or enable any new public service.

### InstaGet Herald acceptance (2026-08-25 baseline)

The accepted baseline used ReachSocial commit `50d5284fddb3f04527b3566a3950b5622cb68ece`
on Herald as image digest
`sha256:8b3a284399a750014a20651bfb50a9091a7f52197360fbd58ca5b2c1d5455ed0`.
The deployment contract now entitles the internal `InstaGet-Herald` client to
`news.person` plus the twelve reviewed Instagram, X, TikTok, and YouTube
profile/feed/post services. The client remains unable to call every other
private or public service.

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
