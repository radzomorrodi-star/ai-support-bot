"""Demo betting engine. Every acceptance decision is made server-side from DB state - callback data and
client-supplied numbers are never trusted. Confirmation is one atomic transaction, idempotent per draft."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import compliance
from app.config import Settings
from app.db.models import Bet, BetDraft, Customer, Event, PriceQuote, Receipt
from app.db.session import transaction
from app.money import payout_minor
from app.odds.service import current_quote, is_suspended
from app.services import opconfig, receipts, wallet
from app.services.audit import append_audit


class BetError(Exception):
    code = "generic"

    def __init__(self, code: str | None = None, **info):
        super().__init__(code or self.code)
        self.code = code or self.code
        self.info = info


_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_id(n: int = 10) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


async def create_draft(s: AsyncSession, customer_id: int, quote_id: int, now: datetime, cfg: dict) -> BetDraft:
    q = await s.get(PriceQuote, quote_id)
    if q is None:
        raise BetError("price_unavailable")
    ev = await s.get(Event, q.event_id)
    if ev.status != "scheduled":
        raise BetError("event_not_open")
    if ev.kickoff_utc <= now + timedelta(seconds=cfg["bet_cutoff_s"]):
        raise BetError("event_started")
    if await is_suspended(s, ev.id, q.market):
        raise BetError("suspended")
    cur = await current_quote(s, q.event_id, q.market, q.selection, now)
    if cur is None:
        raise BetError("price_unavailable")
    if cur.odds_milli != q.odds_milli:
        raise BetError("price_changed", odds_milli=cur.odds_milli)
    d = BetDraft(id=new_id(16), customer_id=customer_id, quote_id=cur.id,
                 expires_at=now + timedelta(seconds=cfg["quote_ttl_s"]), created_at=now)
    s.add(d)
    await s.flush()
    return d


async def set_stake(s: AsyncSession, customer_id: int, draft_id: str, stake_minor: int, now: datetime, cfg: dict) -> BetDraft:
    d = await s.get(BetDraft, draft_id)
    if d is None or d.customer_id != customer_id or d.consumed:
        raise BetError("draft_not_found")
    if d.expires_at <= now:
        raise BetError("draft_expired")
    if not cfg["min_stake_minor"] <= stake_minor <= cfg["max_stake_minor"]:
        raise BetError("stake_range")
    if stake_minor > await wallet.balance(s, customer_id):
        raise BetError("insufficient_funds")
    d.stake_minor = stake_minor
    d.expires_at = now + timedelta(seconds=cfg["quote_ttl_s"])   # fresh window to confirm
    return d


async def confirm_bet(sm: async_sessionmaker[AsyncSession], settings: Settings, draft_id: str, customer_id: int,
                      now: datetime) -> tuple[Bet, Receipt, bool]:
    """Returns (bet, receipt, created). created=False means this was a duplicate confirmation."""
    idem = f"draft:{draft_id}"
    async with transaction(sm) as s:
        # 1) Atomically claim the draft. Exactly one concurrent caller wins this UPDATE.
        won = await s.execute(update(BetDraft).where(
            BetDraft.id == draft_id, BetDraft.customer_id == customer_id, BetDraft.consumed.is_(False),
            BetDraft.stake_minor.is_not(None)).values(consumed=True))
        if won.rowcount != 1:
            existing = (await s.execute(select(Bet).where(Bet.idempotency_key == idem,
                                                          Bet.customer_id == customer_id))).scalar()
            if existing:
                rc = await s.get(Receipt, existing.id)
                return existing, rc, False
            raise BetError("draft_not_found")

        _, cfg = await opconfig.load_active(s, settings)      # raises ConfigTampered -> fail closed
        d = await s.get(BetDraft, draft_id)
        if d.expires_at <= now:
            raise BetError("draft_expired")
        # Serialise all of this customer's concurrent confirmations (daily-limit check is read-then-write).
        cust = (await s.execute(select(Customer).where(Customer.telegram_id == customer_id)
                                .with_for_update())).scalar_one()
        if cust.status != "active" or compliance.is_excluded(cust):
            raise BetError("excluded")
        if not compliance.jurisdiction_allowed(cust.country_code, cfg):
            raise BetError("excluded")
        q = await s.get(PriceQuote, d.quote_id)
        ev = await s.get(Event, q.event_id)

        # 2) Re-validate everything against CURRENT server state.
        if ev.status != "scheduled":
            raise BetError("event_not_open")
        if ev.kickoff_utc <= now + timedelta(seconds=cfg["bet_cutoff_s"]):
            raise BetError("event_started")
        if await is_suspended(s, ev.id, q.market):
            raise BetError("suspended")
        cur = await current_quote(s, ev.id, q.market, q.selection, now)
        if cur is None:
            raise BetError("price_unavailable")
        if cur.odds_milli != q.odds_milli:
            raise BetError("price_changed", odds_milli=cur.odds_milli)
        stake = d.stake_minor
        if not cfg["min_stake_minor"] <= stake <= cfg["max_stake_minor"]:
            raise BetError("stake_range")
        if not await compliance.daily_limit_ok(s, cust, cfg, stake):
            raise BetError("limit")

        # 3) Money + immutable records, all in this transaction.
        bet_id = new_id(10)
        try:
            await wallet.apply(s, customer_id, -stake, "stake", f"stake:{bet_id}", "bet", bet_id)
        except wallet.InsufficientFunds:
            raise BetError("insufficient_funds")
        bet = Bet(id=bet_id, customer_id=customer_id, event_id=ev.id, quote_id=cur.id, market=q.market,
                  selection=q.selection, odds_milli=cur.odds_milli, stake_minor=stake,
                  payout_minor=payout_minor(stake, cur.odds_milli), kickoff_utc=ev.kickoff_utc,
                  terms_version=cfg["terms_version"], idempotency_key=idem, status="open", created_at=now)
        s.add(bet)
        await s.flush()
        rc = receipts.make_receipt(settings, receipts.build_body(bet, ev, cust.timezone))
        s.add(rc)
        await append_audit(s, settings, f"customer:{customer_id}", "bet.placed", "bet", bet_id,
                           {"stake_minor": stake, "odds_milli": bet.odds_milli, "event_id": ev.id,
                            "quote_id": cur.id, "receipt_hash": rc.integrity_hash})
        await compliance.monitor_bet_velocity(s, customer_id)
        await s.flush()
        return bet, rc, True
