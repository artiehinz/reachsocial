# Local Instagram normalization fix — 2026-09-26

Prepared on `fix/instagram-profile-normalization-20260926` from `234c666`.
No provider/deployment calls or customer-data writes were made.

`normalized.py` now reads `caption.text`, `like_count`, `play_count` and
`ig_play_count`, accepts the mobile `user` author shape, and normalizes
Instagram types to image/video/carousel. Regression tests preserve zero likes,
multiline captions, the author, and video/poster pairing.

111 non-live tests passed (10 live tests excluded, one existing deprecation
warning). The normalization-focused suite passed again after the final code
cleanup. Runtime response caches are disposable in-memory state; no external
cache invalidation was performed. Already persisted consumer projections need
an authorized fresh fetch after the fix is released.

Companion InstaGet changes and the full local report:
`/tmp/instaget-social-profile-flow-20260926/docs/audits/social-profile-flow-local-20260926.md`.
