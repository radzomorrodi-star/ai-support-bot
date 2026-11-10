"""Outbox delivery of customer notifications (win, loss, void, reminders, claim results)."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import fa
from app.bot import keyboards as K
from app.db.base import utcnow
from app.db.models import Bet, Customer, Event, Notification

log = logging.getLogger("bot.notifier")
T = fa.T


async def _render(s: AsyncSession, n: Notification, tz: str):
    p = n.payload
    bet = await s.get(Bet, p["bet_id"]) if "bet_id" in p else None
    ev = await s.get(Event, bet.event_id) if bet else None
    title = fa.match_title(ev.home, ev.away) if ev else ""
    amt = fa.money(p["amount_minor"]) if "amount_minor" in p else ""
    dl = fa.jdatetime_full(datetime.fromisoformat(p["deadline"]), tz) if "deadline" in p else ""
    if n.kind == "win":
        return T["win_notice"].format(bet=p["bet_id"], title=title, amount=amt, deadline=dl), K.claim_kb(p["bet_id"])
    if n.kind == "claim_reminder":
        return T["claim_reminder"].format(bet=p["bet_id"], amount=amt, deadline=dl), K.claim_kb(p["bet_id"])
    if n.kind == "claim_review":
        return T["claim_review"].format(bet=p["bet_id"], amount=amt), K.claim_kb(p["bet_id"])
    if n.kind == "loss":
        return T["loss_notice"].format(bet=p["bet_id"], title=title), K.home_only()
    if n.kind == "void":
        return T["void_notice"].format(bet=p["bet_id"], title=title, amount=amt), K.home_only()
    if n.kind == "claim_result":
        word = "✅ تأیید و به کیف پول آزمایشی واریز شد" if p["approved"] else "❌ رد شد"
        return f"🎁 نتیجهٔ درخواست جایزه ({p['bet_id']}): {word}\n{amt}", K.home_only()
    return None, None


async def drain(bot, sm: async_sessionmaker[AsyncSession], limit: int = 50) -> int:
    sent = 0
    async with sm() as s:
        items = (await s.execute(select(Notification).where(Notification.sent_at.is_(None), Notification.attempts < 5)
                                 .order_by(Notification.id).limit(limit))).scalars().all()
        for n in items:
            c = await s.get(Customer, n.customer_id)
            text, kb = await _render(s, n, c.timezone)
            n.attempts += 1
            if text is None:
                n.sent_at = utcnow()
                continue
            try:
                await bot.send_message(n.customer_id, text, reply_markup=kb)
                n.sent_at = utcnow()
                sent += 1
            except TelegramForbiddenError:        # user blocked the bot: stop retrying
                n.attempts = 99
            except TelegramAPIError as e:
                log.warning("notify failed", extra={"err": type(e).__name__})
        await s.commit()
    return sent
