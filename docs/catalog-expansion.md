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

Use the actual ScrapeCreators pack values to calculate the conservative cost
snapshot for the five validation services:

```bash
uv run python scripts/calculate_scrapecreators_cost.py \
  --pack-price-usd <actual-price> --credits <actual-credit-count>
```

The result alone does not make a service available. A credential-gated live
contract sample and sanitized evidence are still required for each response
shape.

## Delivery batches

1. Publish the already validated X and TikTok contracts after the actual
   ScrapeCreators credit price is recorded.
2. Close InstaGet gaps: Instagram profile posts, Instagram stories, X latest
   feed, TikTok feed, and LinkedIn enrichment.
3. Add high-value research services: Instagram/TikTok comments and transcripts,
   then YouTube channel/video/search/comments/transcripts.
4. Add Facebook, Reddit, LinkedIn company/post, and selected ad-library tools.
5. Review newer and long-tail platforms independently.

Apify is not treated as one bulk catalog. Each selected Actor requires its own
permission, schema, bounded-run, cost, reliability, and maintainer review.
