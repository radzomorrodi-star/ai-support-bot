"""Composition root: builds engine, providers, odds service, result sources and (optionally) the bot."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.session import create_all, make_engine, make_sessionmaker, transaction
from app.odds.providers.base import OddsProvider
from app.odds.providers.mock import MockOddsProvider
from app.odds.providers.theoddsapi import TheOddsApiProvider
from app.odds.service import OddsService, seed_competitions
from app.ratelimit import KV, MemoryKV
from app.results.sources import ProviderResultSource, ResultSource
from app.services import opconfig


@dataclass
class Runtime:
    settings: Settings
    engine: AsyncEngine
    sm: async_sessionmaker[AsyncSession]
    kv: KV
    odds: OddsService
    sources: list[ResultSource]
    providers: list[OddsProvider] = field(default_factory=list)
    bot: Any = None
    dp: Any = None

    async def close(self) -> None:
        for p in self.providers:
            await p.aclose()
        if self.bot:
            await self.bot.session.close()
        await self.engine.dispose()


def make_provider(name: str, settings: Settings, sm) -> OddsProvider:
    if name == "mock":
        return MockOddsProvider()
    if name == "the_odds_api":
        if not settings.the_odds_api_key:
            raise RuntimeError("THE_ODDS_API_KEY is required for the_odds_api")
        return TheOddsApiProvider(settings.the_odds_api_key.get_secret_value(), settings.odds_regions,
                                  settings.odds_http_timeout_seconds, sm)
    raise RuntimeError(f"unknown odds provider: {name!r} (supported: mock, the_odds_api)")


async def build(settings: Settings, with_bot: bool = True) -> Runtime:
    settings.require_prod_secrets()
    engine = make_engine(settings.database_url)
    if settings.environment != "prod" and settings.database_url.startswith("sqlite"):
        await create_all(engine)          # dev convenience; Postgres always goes through Alembic
    sm = make_sessionmaker(engine)
    async with transaction(sm) as s:
        await seed_competitions(s)
        await opconfig.ensure_initial(s, settings)

    primary = make_provider(settings.odds_primary_provider, settings, sm)
    fallback = make_provider(settings.odds_fallback_provider, settings, sm) if settings.odds_fallback_provider else None
    providers = [p for p in (primary, fallback) if p]
    if primary.name == "mock":     # DEMO: two named views of the synthetic feed stand in for two sources
        sources: list[ResultSource] = [ProviderResultSource(primary, "mock_a"), ProviderResultSource(primary, "mock_b")]
    else:
        sources = [ProviderResultSource(p) for p in providers]   # a 2nd independent source must be contracted

    if settings.redis_url:
        from redis.asyncio import Redis
        kv: KV = Redis.from_url(settings.redis_url)
    else:
        if settings.environment == "prod":
            raise RuntimeError("REDIS_URL is required in prod")
        kv = MemoryKV()

    rt = Runtime(settings, engine, sm, kv, OddsService(sm, settings, primary, fallback), sources, providers)
    if with_bot and settings.bot_token:
        from app.bot.setup import make_bot, make_dispatcher, make_storage
        storage, _ = make_storage(settings)
        rt.bot = make_bot(settings)
        rt.dp = make_dispatcher(settings, sm, storage, kv)
    return rt
