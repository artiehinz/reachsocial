#!/usr/bin/env python3
"""Print a safe, operator-readable ScrapeCreators credit-budget snapshot.

The provider key stays in the process environment.  The command deliberately
does not make a purchase, write a top-up setting, or print the provider reply.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import httpx

from reachsocial.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--internal-reserve",
        type=int,
        required=True,
        help="credits reserved for existing InstaGet use",
    )
    args = parser.parse_args()
    if args.internal_reserve < 0:
        parser.error("--internal-reserve must be zero or greater")
    key = get_settings().scrapecreators_api_key
    if not key:
        raise SystemExit("SCRAPECREATORS_API_KEY is not configured")
    response = httpx.get(
        "https://api.scrapecreators.com/v1/account/credit-balance",
        headers={"x-api-key": key},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    remaining = payload.get("credits_remaining", payload.get("creditCount"))
    if not isinstance(remaining, int) or remaining < 0:
        raise SystemExit("provider returned no usable remaining-credit count")
    print(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "credits_remaining": remaining,
                "internal_reserve": args.internal_reserve,
                "public_capacity": max(0, remaining - args.internal_reserve),
                "launch_ready": remaining > args.internal_reserve,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
