from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app import fa
from app.db.session import transaction
from app.ratelimit import KV, allow, first_seen
from app.services import customers, opconfig

log = logging.getLogger("bot.mw")


class UpdateDedupe(BaseMiddleware):
    """Replay protection: each Telegram update_id is processed at most once (Redis SET NX)."""

    def __init__(self, kv: KV):
        self.kv = kv

    async def __call__(self, handler, event: Update, data: dict[str, Any]):
        if not await first_seen(self.kv, f"upd:{event.update_id}"):
            log.info("duplicate update dropped")
            return None
        return await handler(event, data)


class Throttle(BaseMiddleware):
    def __init__(self, kv: KV, limit: int = 20, window_s: int = 10):
        self.kv, self.limit, self.window = kv, limit, window_s

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        user = getattr(event, "from_user", None)
        if user is None:
            return None
        if not await allow(self.kv, f"user:{user.id}", self.limit, self.window):
            if isinstance(event, CallbackQuery):
                await event.answer(fa.T["err_rate"], show_alert=False)
            elif isinstance(event, Message):
                await event.answer(fa.T["err_rate"])
            return None
        return await handler(event, data)


class Identify(BaseMiddleware):
    """Registers the customer (Telegram id == customer number) and injects the verified config."""

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        user = getattr(event, "from_user", None)
        if user is None or user.is_bot:
            return None
        sm, settings = data["sm"], data["settings"]
        try:
            async with transaction(sm) as s:
                _, cfg = await opconfig.load_active(s, settings)
                customer = await customers.register(s, settings, cfg, user.id, user.username)
        except opconfig.ConfigTampered:
            log.error("config tampered - refusing service")
            if isinstance(event, CallbackQuery):
                await event.answer(fa.T["err_generic"], show_alert=True)
            elif isinstance(event, Message):
                await event.answer(fa.T["err_generic"])
            return None
        if customer.status != "active":
            return None
        data["customer"], data["cfg"] = customer, cfg
        return await handler(event, data)
