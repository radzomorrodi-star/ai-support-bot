"""Screens: each function reads server state and returns (text, keyboard)."""
from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fa
from app.bot import keyboards as K
from app.db.models import Bet, Claim, Competition, Customer, Event, EventOutcome, PriceQuote, Receipt
from app.odds.normalize import MARKET_SELECTIONS
from app.odds.service import bettable_events, market_view
from app.services import receipts, wallet

T = fa.T
_EMOJI = {("1x2", "home"): "🔵", ("1x2", "draw"): "⚪", ("1x2", "away"): "🔴",
          ("ou25", "over"): "🔼", ("ou25", "under"): "🔽", ("btts", "yes"): "✅", ("btts", "no"): "❌"}
Screen = tuple[str, InlineKeyboardMarkup]


async def home(s: AsyncSession, c: Customer) -> Screen:
    return T["welcome"].format(cid=c.telegram_id, bal=fa.money(await wallet.balance(s, c.telegram_id))), K.main_menu()


async def leagues(s: AsyncSession) -> Screen:
    comps = (await s.execute(select(Competition).where(Competition.enabled.is_(True)))).scalars().all()
    rows, row = [], []
    for c in comps:
        row.append(K.b("🏆 " + fa.COMP_FA.get(c.key, c.name_en), "cp", c.key))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(K.nav())
    return T["choose_comp"], K.kb(rows)


def _event_button(e: Event, tz: str) -> list:
    label = f"⚽ {fa.match_title(e.home, e.away, plain=True)} • {fa.jdate(e.kickoff_utc, tz)} {fa.jtime(e.kickoff_utc, tz)}"
    return [K.b(label, "ev", str(e.id))]


async def matches(s: AsyncSession, c: Customer, comp_key: str | None, now: datetime, cutoff_s: int) -> Screen:
    keys = [comp_key] if comp_key else [x for x in (await s.execute(select(Competition.key))).scalars()]
    evs: list[Event] = []
    for k in keys:
        evs += await bettable_events(s, k, now, cutoff_s)
    evs.sort(key=lambda e: e.kickoff_utc)
    evs = evs[:12]
    back = ("lg", None) if comp_key else None
    if not evs:
        return T["no_matches"], K.kb([K.nav(back)])
    rows = [_event_button(e, c.timezone) for e in evs]
    rows.append(K.nav(back))
    return T["choose_match"], K.kb(rows)


async def event_card(s: AsyncSession, c: Customer, event_id: int, market: str, now: datetime) -> Screen | None:
    ev = await s.get(Event, event_id)
    if ev is None or ev.status != "scheduled" or ev.kickoff_utc <= now:
        return None
    qs = await market_view(s, ev.id, market, now)
    back = ("cp", ev.competition_key)
    if not qs:
        return T["err_suspended"], K.kb([K.nav(back)])
    lines = []
    sel_rows = []
    for q in qs:
        lbl = fa.selection_label(q.market, q.selection, ev.home, ev.away)
        lines.append(f"{_EMOJI[(q.market, q.selection)]} {lbl} — {fa.odds(q.odds_milli)}")
        sel_rows.append(K.b(f"{_EMOJI[(q.market, q.selection)]} {fa.selection_label(q.market, q.selection, ev.home, ev.away, True)} — {fa.odds(q.odds_milli)}",
                            "sl", str(q.id)))
    n_min = min(q.n_quotes for q in qs)
    text = T["match_card"].format(
        title=fa.match_title(ev.home, ev.away), comp=fa.COMP_FA.get(ev.competition_key, ev.competition_key),
        date=fa.jdate(ev.kickoff_utc, c.timezone), time=fa.jtime(ev.kickoff_utc, c.timezone),
        market=fa.MARKET_FA[market]) + "\n\n" + "\n".join(lines)
    text += f"\n\n📚 تعداد منابع معتبر قیمت: {fa.digits(str(n_min))}\n{T['price_note']}"
    rows = [[b] for b in sel_rows]
    other = [m for m in MARKET_SELECTIONS if m != market]
    rows.append([K.b("📊 " + fa.MARKET_FA[m], "mk", f"{ev.id}:{m}") for m in other])
    rows.append([K.b("🔍 جزئیات قیمت‌گذاری", "dt", f"{ev.id}:{market}")])
    rows.append(K.nav(back))
    return text, K.kb(rows)


async def price_detail(s: AsyncSession, event_id: int, market: str, now: datetime) -> Screen | None:
    ev = await s.get(Event, event_id)
    qs = await market_view(s, event_id, market, now) if ev else None
    if not qs:
        return None
    lines = [f"🔍 جزئیات قیمت‌گذاری — {fa.MARKET_FA[market]}", ""]
    for q in qs:
        lines.append(f"{fa.selection_label(q.market, q.selection, ev.home, ev.away)}\n"
                     f"   بهترین قیمت بازار: {fa.odds(q.best_milli)} | میانه بازار: {fa.odds(q.median_milli)}\n"
                     f"   قیمت پیشنهادی سامانه: {fa.odds(q.odds_milli)} | تعداد منابع معتبر: {fa.digits(str(q.n_quotes))}")
    lines += ["", f"حاشیهٔ سامانه: {fa.pct_bp(qs[0].margin_bp)} (روی احتمال‌های بدون حاشیه)",
              f"مجموع احتمال ضمنی قیمت‌های سامانه: {fa.pct_bp(qs[0].calc.get('customer_overround_bp', 0))}",
              "", T["price_note"]]
    return "\n".join(lines), K.kb([K.nav(("ev", str(event_id)))])


async def my_bets(s: AsyncSession, cid: int) -> Screen:
    bets = (await s.execute(select(Bet).where(Bet.customer_id == cid).order_by(Bet.created_at.desc()).limit(10))).scalars().all()
    if not bets:
        return T["no_bets"], K.kb([K.nav()])
    rows = []
    for bt in bets:
        ev = await s.get(Event, bt.event_id)
        icon = fa.STATUS_FA[bt.status].split()[0]
        rows.append([K.b(f"{icon} {fa.match_title(ev.home, ev.away, plain=True)} • {fa.money(bt.stake_minor)}", "bt", bt.id)])
    rows.append(K.nav())
    return T["my_bets"], K.kb(rows)


async def bet_detail(s: AsyncSession, cid: int, bet_id: str) -> Screen | None:
    bet = (await s.execute(select(Bet).where(Bet.id == bet_id, Bet.customer_id == cid))).scalar()   # ownership enforced
    if bet is None:
        return None
    rc = await s.get(Receipt, bet.id)
    text = receipts.render(rc, bet.status)
    claim = (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar()
    if claim:
        text += f"\n\n🎁 وضعیت جایزه: {fa.CLAIM_STATUS_FA[claim.status]}"
        if claim.status in ("pending_request", "admin_review"):
            return text, K.claim_kb(bet.id)
    return text, K.kb([[K.b(fa.BTN["mybets"], "mb"), K.b(fa.BTN["home"], "h")]])


async def results(s: AsyncSession) -> Screen:
    rows = (await s.execute(select(EventOutcome, Event).join(Event, Event.id == EventOutcome.event_id)
                            .where(EventOutcome.final_status.in_(("finished", "postponed", "cancelled", "abandoned")))
                            .order_by(EventOutcome.id.desc()).limit(10))).all()
    seen, lines = set(), []
    for o, e in rows:
        if e.id in seen:
            continue
        seen.add(e.id)
        score = (f"{fa.digits(str(o.home_goals))} - {fa.digits(str(o.away_goals))}" if o.final_status == "finished"
                 else fa.EVENT_STATUS_FA[o.final_status])
        lines.append(f"⚽ {fa.match_title(e.home, e.away)}  ➜  {score}")
    if not lines:
        return T["no_results"], K.kb([K.nav()])
    return T["results"] + "\n\n" + "\n".join(lines), K.kb([K.nav()])


async def wallet_screen(s: AsyncSession, cid: int) -> Screen:
    return T["wallet"].format(bal=fa.money(await wallet.balance(s, cid))), K.kb([K.nav()])


def terms(version: str) -> Screen:
    return T["terms"].format(ver=fa.digits(version)), K.kb([K.nav()])
