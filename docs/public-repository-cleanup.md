# Companion repository cleanup — 2026-10-11

The companion repository is `artiehinz/ReachSocial.dev`. It must contain only
client-facing documentation and branding. The private application repository
remains `artiehinz/reachsocial`; do not mirror it to the companion repository.

The companion repository was already private when this cleanup began. Its
default branch was replaced with an independent root commit containing exactly:

- README.md
- docs/usage.md
- assets/logo.svg
- assets/logo-light.svg
- LICENSE (documentation)
- .gitignore (explicit file allowlist)

The independent checkout is
`/mnt/instaget-nvme/herald-work/reachsocial-public-docs.xDAt7C`.
GitHub Actions are disabled. Four copied workflow runs, one Actions cache, and
two deployment records were deleted. There were no tags, pull refs, forks,
issues, releases, or Actions artifacts returned by the corresponding checks.

After replacing main, authenticated GitHub API access could still resolve old
commit `e66fcf3a2b518928c321536a61ead249623f2ea2`. A clean default branch does
not remove server-retained objects. Keep the repository private until that
retained history has been addressed. Do not promise that previously downloaded
copies or third-party caches can be recalled.

GitHub documents the remaining limitation here:
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository

## Draft for the owner to send to GitHub Support

Repository: artiehinz/ReachSocial.dev

This repository accidentally included our private backend source and operating
documentation. It is now private. We replaced main with an independent,
documentation-only root commit, removed workflow runs, caches and deployment
records, and disabled Actions. There are no pull requests or known forks.

The old commit e66fcf3a2b518928c321536a61ead249623f2ea2 remains accessible through
the authenticated API. Please advise whether you can purge the unreachable
historical objects and cached views before we reopen this documentation repo.

GitHub determines eligibility for support-assisted removal; its documentation
says non-sensitive data is not eligible. This draft has not been sent.
