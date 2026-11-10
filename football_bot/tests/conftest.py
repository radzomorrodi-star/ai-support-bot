from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import Settings
from app.db.models import Event
from app.db.session import create_all, make_engine, make_sessionmaker, transaction
from app.odds.providers.mock import MockOddsProvider
from app.odds.service import OddsService, seed_competitions
from app.services import betting, customers, opconfig


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


PG_URL = os.environ.get("TEST_DATABASE_URL")   # e.g. postgresql+asyncpg://user:pw@127.0.0.1/db (migrated with Alembic)
IS_PG = bool(PG_URL)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, environment="test", database_url=PG_URL or f"sqlite+aiosqlite:///{tmp_path}/t.db",
                    secrets_key=Fernet.generate_key().decode(), receipt_hmac_key="r" * 40,
                    config_signing_key="c" * 40, audit_hmac_key="a" * 40, admin_allowlist="9001,9002",
                    webhook_secret_token="w" * 40, webhook_path_secret="p" * 40)


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))


@pytest_asyncio.fixture
async def sm(settings):
    engine = make_engine(settings.database_url)
    if IS_PG:   # schema (incl. immutability triggers) comes from Alembic; just empty the tables
        from sqlalchemy import text
        from app.db.base import Base
        names = ",".join(t.name for t in Base.metadata.sorted_tables)
        async with engine.begin() as c:
            await c.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    else:
        await create_all(engine)
    sm = make_sessionmaker(engine)
    async with transaction(sm) as s:
        await seed_competitions(s)
        await opconfig.ensure_initial(s, settings)
    yield sm
    await engine.dispose()


@pytest_asyncio.fixture
async def world(sm, settings, clock):
    provider = MockOddsProvider()
    svc = OddsService(sm, settings, provider, clock=clock)
    res = await svc.refresh_all()
    assert all(v.startswith("ok") for v in res.values()), res
    async with sm() as s:
        ev = (await s.execute(select(Event).where(Event.competition_key == "epl").order_by(Event.kickoff_utc))).scalars().first()
    return SimpleNamespace(sm=sm, settings=settings, clock=clock, provider=provider, svc=svc, event_id=ev.id)


async def register(w, cid: int = 111):
    async with transaction(w.sm) as s:
        _, cfg = await opconfig.load_active(s, w.settings)
        return await customers.register(s, w.settings, cfg, cid, "tester")


async def make_draft(w, cid: int, market="1x2", selection="home", stake=1000, event_id=None):
    """Create a draft with a stake via the same service calls the bot uses."""
    from app.odds.service import current_quote
    async with transaction(w.sm) as s:
        _, cfg = await opconfig.load_active(s, w.settings)
        q = await current_quote(s, event_id or w.event_id, market, selection, w.clock())
        d = await betting.create_draft(s, cid, q.id, w.clock(), cfg)
        await betting.set_stake(s, cid, d.id, stake, w.clock(), cfg)
        return d.id, q


async def place(w, cid=111, **kw):
    did, _ = await make_draft(w, cid, **kw)
    return await betting.confirm_bet(w.sm, w.settings, did, cid, w.clock())


async def bypass_triggers(s) -> None:
    """Simulate a privileged attacker/DBA: on PostgreSQL disable the append-only triggers for this transaction."""
    if IS_PG:
        from sqlalchemy import text
        await s.execute(text("SET LOCAL session_replication_role = replica"))
