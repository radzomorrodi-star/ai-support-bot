"""Background worker: odds refresh, result ingestion, settlement, claim reminders, notifications, housekeeping.
Each job takes a short Redis lock so running several workers is safe (jobs are idempotent regardless)."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete

from app.bot.notifier import drain
from app.config import get_settings
from app.db.base import utcnow
from app.db.models import AdminSession, ApiUsage, BetDraft, ProcessedUpdate
from app.db.session import transaction
from app.logging import setup_logging
from app.odds.service import mark_started_events
from app.runtime import Runtime, build
from app.services import claims, opconfig, settlement

log = logging.getLogger("worker")


async def _locked(rt: Runtime, name: str, ttl: int, fn) -> None:
    if not await rt.kv.set(f"lock:{name}", "1", nx=True, ex=ttl):
        return
    try:
        await fn()
    except opconfig.ConfigTampered:
        log.error("config tampered: job skipped", extra={"job": name})
    except Exception:
        log.exception("job failed", extra={"job": name})


async def every(seconds: int, coro_fn) -> None:
    while True:
        await coro_fn()
        await asyncio.sleep(seconds)


async def run(rt: Runtime) -> None:
    s = rt.settings

    async def refresh():
        await _locked(rt, "odds", max(30, s.odds_refresh_seconds - 5), lambda: _log(rt.odds.refresh_all(), "odds_refresh"))

    async def results():
        async def go():
            now = utcnow()
            async with transaction(rt.sm) as db:
                await mark_started_events(db, now)
            await settlement.ingest_results(rt.sm, rt.sources, now)
            log.info("decide", extra=await settlement.decide_outcomes(rt.sm, s, now))
            n = await settlement.settle_pending(rt.sm, s, now)
            if n:
                log.info("settled", extra={"bets": n})
        await _locked(rt, "settle", 240, go)

    async def claim_sweep():
        async def go():
            async with rt.sm() as db:
                _, cfg = await opconfig.load_active(db, s)
            log.info("claims", extra=await claims.sweep(rt.sm, s, cfg, utcnow()))
        await _locked(rt, "claims", 540, go)

    async def notify():
        if rt.bot:
            await _locked(rt, "notify", 10, lambda: drain(rt.bot, rt.sm))

    async def housekeeping():
        async def go():
            now = utcnow()
            async with transaction(rt.sm) as db:       # data-retention: operational tables only
                await db.execute(delete(ProcessedUpdate).where(ProcessedUpdate.ts < now - timedelta(days=2)))
                await db.execute(delete(ApiUsage).where(ApiUsage.ts < now - timedelta(days=90)))
                await db.execute(delete(AdminSession).where(AdminSession.expires_at < now - timedelta(days=1)))
                # drafts are ephemeral (bets keep only the idempotency key string, not an FK)
                await db.execute(delete(BetDraft).where(BetDraft.expires_at < now - timedelta(days=1)))
        await _locked(rt, "housekeeping", 3000, go)

    jobs = [every(s.odds_refresh_seconds, refresh), every(300, results), every(600, claim_sweep),
            every(15, notify), every(3600, housekeeping)]
    if rt.bot and rt.dp and s.telegram_mode == "polling":
        await rt.bot.delete_webhook(drop_pending_updates=False)
        jobs.append(rt.dp.start_polling(rt.bot, handle_signals=False))
    await asyncio.gather(*jobs)


async def _log(coro, name):
    log.info(name, extra={"result": await coro})


async def main() -> None:
    setup_logging()
    rt = await build(get_settings(), with_bot=True)
    try:
        await run(rt)
    finally:
        await rt.close()


if __name__ == "__main__":
    asyncio.run(main())
