"""Create a ReachSocial B2B client and print its API key exactly once."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from reachsocial.config import get_settings
from reachsocial.db import SessionLocal, init_db
from reachsocial.models import Client
from reachsocial.security import generate_api_key, hash_api_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--billing-mode", default="internal")
    parser.add_argument("--rate-limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--daily-spend-cents", type=int, default=None)
    args = parser.parse_args()
    settings = get_settings()
    init_db()
    with SessionLocal() as session:
        if session.scalar(select(Client).where(Client.name == args.name)):
            raise SystemExit(f"Client {args.name!r} already exists")
        api_key = generate_api_key()
        session.add(
            Client(
                name=args.name,
                api_key_hash=hash_api_key(api_key),
                billing_mode=args.billing_mode,
                rate_limit_per_minute=args.rate_limit or settings.default_rate_limit_per_minute,
                concurrency_limit=args.concurrency or settings.default_concurrency_limit,
                daily_spend_cents=args.daily_spend_cents or settings.default_daily_spend_cents,
            )
        )
        session.commit()
    print(f"Created client {args.name}. Store this key securely; it will not be shown again:")
    print(api_key)


if __name__ == "__main__":
    main()
