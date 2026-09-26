# Cross-platform normalization audit — local only, 2026-09-26

Continues the uncommitted Instagram fix on the same branch. Fixes cover typed
media URL fallback, TikTok media/posters/photo slides/author/stats, stable X
numeric author IDs and MP4 selection, preserved quote/bookmark counts,
YouTube channel-ID routing, missing-author isolation and meaningful handle-only
profile acceptance. Empty profiles remain rejected.

Full service-by-service report and consumer changes:
`/tmp/instaget-social-profile-flow-20260926/docs/audits/social-api-cross-platform-20260926.md`.

Final non-live suite: 126 passed, 10 live tests excluded, one existing warning.
Evidence: `/tmp/reachsocial-cross-platform-tests-final.log`.
No provider requests, deployment or stored-data repair. Previously lost fields
need authorized refetching; historical wrong identities need separate review.
