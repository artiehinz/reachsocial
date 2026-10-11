# Catalog expansion policy

ReachSocial can cover the ScrapeCreators catalog, but it does not publish raw
provider routes. The official OpenAPI inventory is converted into a sanitized,
review-only engineering queue with:

```bash
uv run python scripts/inventory_scrapecreators.py \
  --output docs/generated/scrapecreators-candidate-inventory.json
```

The generated inventory contains no credential and does not change
`config/services.yaml`. An entry becomes a ReachSocial service only after it
has a stable service ID, validated inputs, a provider-neutral response shape,
sanitized fixtures, error and pagination behavior, a real provider cost sample,
a hard spend limit, a margin-safe price, and explicit publication approval.

`GET /v1/catalog` is the sanitized public roadmap. It intentionally contains a
much smaller curated set than the generated engineering inventory. The status
values are:

- `available`: executable and listed by `GET /v1/services`;
- `validation`: adapter and normalization exist, but a release gate is open;
- `planned`: reviewed product candidate without an accepted contract; and
- `paused`: a known provider, contract, cost, or policy blocker exists.

Use the documented replacement price and observed provider-unit consumption to
calculate the conservative cost snapshot for a validation service. Record an
actual acquisition expense separately if a future pack is purchased:

```bash
uv run python scripts/calculate_scrapecreators_cost.py \
  --pack-price-usd <actual-price> --credits <actual-credit-count>
```

The result alone does not make a service available. A credential-gated live
contract sample and sanitized evidence are still required for each response
shape.

## Current release batches

The 2026-10-11 bounded run verified X, TikTok, Instagram feed/highlight,
YouTube, Facebook, and Reddit contracts. Those services still need staged paid
acceptance and 24-hour reconciliation before public promotion.

`linkedin.profile` is the only active migration dependency: its
ScrapeCreators endpoint currently returns `not_found` for the tested public
profiles. `news.person` needs a successful GDELT availability sample after its
rate limit. Instagram current stories remains paused until ScrapeCreators offers
an acceptable bounded contract. Comments, transcripts, search, and broader
catalog work are outside this release.

Apify is retired from active catalog services. Completed historical results
remain recoverable, but no new service may introduce an Actor without a new
separate decision.
