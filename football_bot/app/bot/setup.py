from __future__ import annotations

from typing import Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.handlers import main as handlers
from app.bot.middlewares import Identify, Throttle, UpdateDedupe
from app.config import Settings
from app.db.base import utcnow
from app.ratelimit import KV, MemoryKV


def make_bot(settings: Settings) -> Bot:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not set")
    return Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def make_storage(settings: Settings) -> tuple[BaseStorage, KV]:
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage
        from redis.asyncio import Redis
        r = Redis.from_url(settings.redis_url)
        return RedisStorage(r), r
    if settings.environment == "prod":
        raise RuntimeError("REDIS_URL is required in prod")
    return MemoryStorage(), MemoryKV()


def make_dispatcher(settings: Settings, sm: async_sessionmaker[AsyncSession], storage: BaseStorage, kv: KV,
                    clock: Callable = utcnow) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    dp.workflow_data.update(sm=sm, settings=settings, clock=clock, kv=kv)
    dp.update.outer_middleware(UpdateDedupe(kv))
    for obs in (dp.message, dp.callback_query):
        obs.middleware(Throttle(kv))
        obs.middleware(Identify())
    dp.include_router(handlers.build_router())
    return dp
