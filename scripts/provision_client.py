"""Idempotently provision a scoped B2B client without printing its API key."""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from reachsocial.config import get_settings
from reachsocial.db import SessionLocal, init_db
from reachsocial.models import Client, ClientService
from reachsocial.security import api_key_id, hash_api_key, verify_api_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--api-key-stdin", action="store_true", required=True)
    parser.add_argument("--service", action="append", required=True)
    parser.add_argument("--rate-limit", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()

    raw_key = sys.stdin.readline().strip()
    key_id = api_key_id(raw_key)
    if key_id is None:
        raise SystemExit("Refusing an invalid ReachSocial API key")

    settings = get_settings()
    init_db()
    with SessionLocal() as session:
        client = session.scalar(select(Client).where(Client.name == args.name))
        if client is None:
            client = Client(
                name=args.name,
                key_id=key_id,
                api_key_hash=hash_api_key(raw_key),
                billing_mode="internal",
                rate_limit_per_minute=max(1, args.rate_limit),
                concurrency_limit=max(1, args.concurrency),
                daily_spend_cents=settings.default_daily_spend_cents,
            )
            session.add(client)
            session.flush()
        else:
            if not verify_api_key(raw_key, client.api_key_hash):
                client.key_id = key_id
                client.api_key_hash = hash_api_key(raw_key)
            client.status = "active"
            client.billing_mode = "internal"
            client.rate_limit_per_minute = max(1, args.rate_limit)
            client.concurrency_limit = max(1, args.concurrency)

        desired = set(args.service)
        existing = {
            row.service_id: row
            for row in session.scalars(
                select(ClientService).where(ClientService.client_id == client.id)
            )
        }
        for service_id in desired:
            row = existing.get(service_id)
            if row is None:
                session.add(
                    ClientService(
                        client_id=client.id,
                        service_id=service_id,
                        enabled=True,
                    )
                )
            else:
                row.enabled = True
        for service_id, row in existing.items():
            if service_id not in desired:
                row.enabled = False
        session.commit()

    print(
        f"Provisioned {args.name} with {len(desired)} scoped service entitlement(s); "
        "the API key was not printed."
    )


if __name__ == "__main__":
    main()
