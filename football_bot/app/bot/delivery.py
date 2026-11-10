"""Receipt delivery + pinning. Pinning is best-effort: failure never affects the bet or the stored receipt."""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Receipt
from app.services import receipts

log = logging.getLogger("bot.delivery")


async def deliver_receipt(bot, sm: async_sessionmaker[AsyncSession], chat_id: int, rc: Receipt, status: str) -> str:
    """Send the receipt and try to pin it. Returns 'pinned' | 'failed' | 'unsent'."""
    text = receipts.render(rc, status)
    try:
        msg = await bot.send_message(chat_id=chat_id, text=text)
    except TelegramAPIError:
        await _mark(sm, rc.bet_id, None, "failed")
        return "unsent"
    pin = "pinned"
    try:
        # Private chats: the bot may pin without admin rights; other chat types would need rights.
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
    except Exception as e:   # permission errors, user deleted chat, API outage - all non-fatal
        log.info("pin failed", extra={"err": type(e).__name__})
        pin = "failed"
    await _mark(sm, rc.bet_id, msg.message_id, pin)
    return pin


async def _mark(sm, bet_id: str, message_id: int | None, pin: str) -> None:
    async with sm() as s:
        await s.execute(update(Receipt).where(Receipt.bet_id == bet_id).values(
            telegram_message_id=message_id, pin_status=pin))
        await s.commit()
