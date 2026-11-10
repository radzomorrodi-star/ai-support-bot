"""Operator CLI.  python -m app.cli bootstrap | create-admin --telegram-id N --role superadmin | verify-audit"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker, transaction
from app.odds.service import seed_competitions
from app.services import opconfig
from app.services.audit import verify_chain


async def _run(args) -> int:
    settings = get_settings()
    settings.require_prod_secrets()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    try:
        if args.cmd == "bootstrap":
            if settings.environment != "prod" and settings.database_url.startswith("sqlite"):
                from app.db.session import create_all
                await create_all(engine)       # dev convenience only; PostgreSQL uses `alembic upgrade head`
            async with transaction(sm) as s:
                await seed_competitions(s)
                await opconfig.ensure_initial(s, settings)
            print("competitions + signed default configuration ready")
        elif args.cmd == "create-admin":
            from app import admin_auth
            pw = getpass.getpass("New admin password (min 12 chars): ")
            if pw != getpass.getpass("Repeat: "):
                print("passwords differ")
                return 1
            async with transaction(sm) as s:
                uri = await admin_auth.create_admin(s, settings, args.telegram_id, args.role, pw)
            print("Scan this in an authenticator app NOW (it is shown only once):\n" + uri)
        elif args.cmd == "verify-audit":
            async with sm() as s:
                ok, bad = await verify_chain(s, settings)
            print("audit chain OK" if ok else f"AUDIT CHAIN BROKEN at id {bad}")
            return 0 if ok else 2
    finally:
        await engine.dispose()
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("verify-audit")
    ca = sub.add_parser("create-admin")
    ca.add_argument("--telegram-id", type=int, required=True)
    ca.add_argument("--role", default="superadmin")
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
