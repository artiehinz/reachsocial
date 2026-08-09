"""Owner-only local CLI for ReachSocial B2B client lifecycle operations."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import func, select

from reachsocial.db import SessionLocal
from reachsocial.models import Client, ClientService, RequestLog
from reachsocial.security import api_key_id, generate_api_key, hash_api_key


def _client(session, name: str) -> Client:  # type: ignore[no-untyped-def]
    row = session.scalar(select(Client).where(Client.name == name))
    if row is None:
        raise SystemExit(f"Client {name!r} does not exist")
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("rotate", "revoke", "activate", "usage"):
        item = commands.add_parser(command)
        item.add_argument("name")
        if command == "rotate":
            item.add_argument("--expires-at", type=datetime.fromisoformat, default=None)
    entitlement = commands.add_parser("entitle")
    entitlement.add_argument("name")
    entitlement.add_argument("service_id")
    entitlement.add_argument("--disable", action="store_true")
    limits = commands.add_parser("limits")
    limits.add_argument("name")
    limits.add_argument("--rate-limit", type=int)
    limits.add_argument("--concurrency", type=int)
    limits.add_argument("--daily-spend-cents", type=int)
    args = parser.parse_args()

    with SessionLocal() as session:
        client = _client(session, args.name)
        if args.command == "rotate":
            raw = generate_api_key()
            client.key_id = api_key_id(raw)
            client.api_key_hash = hash_api_key(raw)
            client.rotated_at = datetime.now(UTC)
            client.api_key_expires_at = args.expires_at
            session.commit()
            print("Store this replacement key securely; it will not be shown again:")
            print(raw)
        elif args.command in {"revoke", "activate"}:
            client.status = "revoked" if args.command == "revoke" else "active"
            session.commit()
            print(f"{client.name}: {client.status}")
        elif args.command == "entitle":
            row = session.scalar(
                select(ClientService).where(
                    ClientService.client_id == client.id,
                    ClientService.service_id == args.service_id,
                )
            )
            if row is None:
                row = ClientService(client_id=client.id, service_id=args.service_id)
                session.add(row)
            row.enabled = not args.disable
            session.commit()
            print(f"{client.name} {args.service_id}: {'enabled' if row.enabled else 'disabled'}")
        elif args.command == "limits":
            if args.rate_limit is not None:
                client.rate_limit_per_minute = args.rate_limit
            if args.concurrency is not None:
                client.concurrency_limit = args.concurrency
            if args.daily_spend_cents is not None:
                client.daily_spend_cents = args.daily_spend_cents
            session.commit()
            print(
                f"{client.name}: rate_limit={client.rate_limit_per_minute} "
                f"concurrency={client.concurrency_limit} "
                f"daily_spend_cents={client.daily_spend_cents}"
            )
        else:
            count, charged, cost = session.execute(
                select(
                    func.count(RequestLog.id),
                    func.coalesce(func.sum(RequestLog.charged_cents), 0),
                    func.coalesce(func.sum(RequestLog.upstream_cost_microusd), 0),
                ).where(RequestLog.client_id == client.id)
            ).one()
            print(
                f"{client.name}: requests={count} charged_cents={charged} "
                f"upstream_cost_microusd={cost}"
            )


if __name__ == "__main__":
    main()
