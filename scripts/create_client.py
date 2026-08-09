"""Create a ReachSocial B2B client and print its API key exactly once."""

from __future__ import annotations

import argparse
from datetime import datetime

from sqlalchemy import select

from reachsocial.config import get_settings
from reachsocial.db import SessionLocal, init_db
from reachsocial.models import Client, ClientService
from reachsocial.security import api_key_id, generate_api_key, hash_api_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--billing-mode", default="internal")
    parser.add_argument("--rate-limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--daily-spend-cents", type=int, default=None)
    parser.add_argument("--expires-at", type=datetime.fromisoformat, default=None)
    parser.add_argument("--service", action="append", default=[])
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
                key_id=api_key_id(api_key),
                api_key_hash=hash_api_key(api_key),
                billing_mode=args.billing_mode,
                rate_limit_per_minute=(
                    args.rate_limit
                    if args.rate_limit is not None
                    else settings.default_rate_limit_per_minute
                ),
                concurrency_limit=(
                    args.concurrency
                    if args.concurrency is not None
                    else settings.default_concurrency_limit
                ),
                daily_spend_cents=(
                    args.daily_spend_cents
                    if args.daily_spend_cents is not None
                    else settings.default_daily_spend_cents
                ),
                api_key_expires_at=args.expires_at,
            )
        )
        session.flush()
        client = session.scalar(select(Client).where(Client.name == args.name))
        for service_id in sorted(set(args.service)):
            session.add(ClientService(client_id=client.id, service_id=service_id, enabled=True))
        session.commit()
    print(f"Created client {args.name}. Store this key securely; it will not be shown again:")
    print(api_key)


if __name__ == "__main__":
    main()
