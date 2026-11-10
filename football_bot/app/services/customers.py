from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Customer, Notification, Wallet
from app.services import wallet


async def register(s: AsyncSession, settings: Settings, cfg: dict[str, Any], telegram_id: int,
                   username: str | None) -> Customer:
    """Telegram user id IS the customer number. Idempotent; safe under concurrent /start."""
    c = await s.get(Customer, telegram_id)
    if c is not None:
        if username and c.username != username[:64]:
            c.username = username[:64]
        return c
    try:
        async with s.begin_nested():
            c = Customer(telegram_id=telegram_id, username=(username or None) and username[:64],
                         timezone=settings.default_timezone, terms_version=cfg["terms_version"])
            s.add(c)
            s.add(Wallet(customer_id=telegram_id, balance_minor=0, is_demo=True))
            await s.flush()
    except IntegrityError:           # lost a registration race
        return await s.get(Customer, telegram_id)
    await wallet.apply(s, telegram_id, cfg["demo_initial_balance_minor"], "demo_grant", f"grant:{telegram_id}")
    return c


async def notify(s: AsyncSession, customer_id: int, kind: str, payload: dict, dedupe_key: str) -> None:
    from sqlalchemy import select
    if (await s.execute(select(Notification.id).where(Notification.dedupe_key == dedupe_key))).first():
        return
    s.add(Notification(customer_id=customer_id, kind=kind, payload=payload, dedupe_key=dedupe_key))
    await s.flush()
