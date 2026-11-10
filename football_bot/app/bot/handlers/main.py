"""Telegram handlers. Thin: parse -> call a service -> render a view. No business rules live here."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import compliance, fa
from app.bot import keyboards as K
from app.bot import views
from app.bot.callbacks import parse
from app.bot.delivery import deliver_receipt
from app.config import Settings
from app.db.models import BetDraft, Complaint, Customer, Event, PriceQuote
from app.db.session import transaction
from app.money import MoneyError, parse_stake
from app.odds.service import current_quote
from app.services import betting, claims, opconfig, wallet
from app.services.audit import append_audit
from app.services.betting import BetError

log = logging.getLogger("bot")
T = fa.T


class Flow(StatesGroup):
    stake = State()
    complaint = State()


ERR = {"event_started": "err_started", "event_not_open": "err_not_open", "suspended": "err_suspended",
       "limit": "err_limit", "excluded": "err_excluded", "draft_expired": "expired", "draft_not_found": "expired",
       "price_unavailable": "expired", "insufficient_funds": "no_funds", "stake_range": "stake_range"}


async def show(target: Message | CallbackQuery, text: str, markup=None) -> None:
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await msg.edit_text(text, reply_markup=markup)
        else:
            await msg.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return
        await msg.answer(text, reply_markup=markup)   # message too old to edit, etc.


def err_text(e: BetError, cfg: dict) -> str:
    if e.code == "price_changed":
        return T["err_price"].format(odds=fa.odds(e.info["odds_milli"]))
    key = ERR.get(e.code, "err_generic")
    t = T[key]
    if key == "stake_range":
        t = t.format(min=fa.money(cfg["min_stake_minor"]), max=fa.money(cfg["max_stake_minor"]))
    elif key == "no_funds":
        t = t.format(bal="")
    return t


async def start(m: Message, state: FSMContext, sm: async_sessionmaker, customer: Customer) -> None:
    await state.clear()
    async with sm() as s:
        text, kb = await views.home(s, customer)
    await m.answer(text, reply_markup=kb)


async def on_callback(cq: CallbackQuery, state: FSMContext, sm: async_sessionmaker, settings: Settings, clock,
                      customer: Customer, cfg: dict, bot: Bot) -> None:
    cb = parse(cq.data)
    if cb is None:                                  # malformed / forged callback data
        await cq.answer(T["err_generic"], show_alert=False)
        async with sm() as s:
            from app.security import security_event
            await security_event(s, "bad_callback_data", "info", actor=str(customer.telegram_id))
            await s.commit()
        return
    await cq.answer()
    now = clock()
    cid = customer.telegram_id
    v, a = cb.verb, cb.arg

    if v == "h":
        await state.clear()
        async with sm() as s:
            await show(cq, *await views.home(s, customer))
    elif v == "lg":
        async with sm() as s:
            await show(cq, *await views.leagues(s))
    elif v in ("ml", "cp"):
        async with sm() as s:
            await show(cq, *await views.matches(s, customer, a if v == "cp" else None, now, cfg["bet_cutoff_s"]))
    elif v in ("ev", "mk"):
        eid, market = (int(a), "1x2") if v == "ev" else (int(a.split(":")[0]), a.split(":")[1])
        async with sm() as s:
            scr = await views.event_card(s, customer, eid, market, now)
        await show(cq, *(scr or (T["err_not_open"], K.home_only())))
    elif v == "dt":
        eid, market = int(a.split(":")[0]), a.split(":")[1]
        async with sm() as s:
            scr = await views.price_detail(s, eid, market, now)
        await show(cq, *(scr or (T["err_suspended"], K.home_only())))
    elif v == "sl":
        await select_outcome(cq, state, sm, cfg, customer, int(a), now)
    elif v == "cf":
        await confirm(cq, state, sm, settings, bot, cfg, customer, a, now)
    elif v == "cx":
        await state.clear()
        async with transaction(sm) as s:
            await s.execute(update(BetDraft).where(BetDraft.id == a, BetDraft.customer_id == cid,
                                                   BetDraft.consumed.is_(False)).values(consumed=True))
        await show(cq, T["cancelled"], K.home_only())
    elif v == "mb":
        async with sm() as s:
            await show(cq, *await views.my_bets(s, cid))
    elif v == "bt":
        async with sm() as s:
            scr = await views.bet_detail(s, cid, a)
        await show(cq, *(scr or (T["err_generic"], K.home_only())))
    elif v == "cl":
        try:
            await claims.request_claim(sm, settings, cid, a, now)
            await show(cq, T["claim_ok"], K.home_only())
        except claims.ClaimDuplicate:
            await show(cq, T["claim_dup"], K.home_only())
        except claims.ClaimNotFound:
            await show(cq, T["err_generic"], K.home_only())
    elif v == "rs":
        async with sm() as s:
            await show(cq, *await views.results(s))
    elif v == "wl":
        async with sm() as s:
            await show(cq, *await views.wallet_screen(s, cid))
    elif v == "tm":
        await show(cq, *views.terms(cfg["terms_version"]))
    elif v == "sp":
        await show(cq, T["support"], K.support_kb())
    elif v == "cm":
        await state.set_state(Flow.complaint)
        await show(cq, T["complaint_ask"], K.home_only())
    elif v == "ex":
        await show(cq, T["excl_ask"], K.exclusion_kb())
    elif v == "exd":
        async with transaction(sm) as s:
            until = await compliance.self_exclude(s, cid, int(a))
            await append_audit(s, settings, f"customer:{cid}", "rg.self_exclusion", "customer", cid, {"days": int(a)})
        await show(cq, T["excl_ok"].format(until=fa.jdate(until, customer.timezone)), K.home_only())
    elif v == "lm":
        await show(cq, "📉 سقف مصرف روزانه را انتخاب کنید (فقط کاهش سقف ممکن است):", K.limit_kb())
    elif v == "dl":
        async with transaction(sm) as s:
            c = await s.get(Customer, cid)
            new = int(a) * 100
            if c.daily_stake_limit_minor is None or new < c.daily_stake_limit_minor:   # customers may only lower it
                c.daily_stake_limit_minor = new
            await append_audit(s, settings, f"customer:{cid}", "rg.daily_limit", "customer", cid, {"limit_minor": new})
        await show(cq, "✅ سقف ثبت شد.", K.home_only())


async def select_outcome(cq, state: FSMContext, sm, cfg, customer, quote_id: int, now) -> None:
    try:
        async with transaction(sm) as s:
            d = await betting.create_draft(s, customer.telegram_id, quote_id, now, cfg)
            q = await s.get(PriceQuote, d.quote_id)
            ev = await s.get(Event, q.event_id)
            bal = await wallet.balance(s, customer.telegram_id)
    except BetError as e:
        await show(cq, err_text(e, cfg), K.home_only())
        return
    await state.set_state(Flow.stake)
    await state.update_data(draft_id=d.id)
    await show(cq, T["ask_stake"].format(
        sel=f"{fa.match_title(ev.home, ev.away)} — {fa.selection_label(q.market, q.selection, ev.home, ev.away)}",
        odds=fa.odds(q.odds_milli), min=fa.money(cfg["min_stake_minor"]), max=fa.money(cfg["max_stake_minor"]),
        bal=fa.money(bal)), K.cancel_kb(d.id))


async def on_stake(m: Message, state: FSMContext, sm: async_sessionmaker, cfg: dict, customer: Customer, clock) -> None:
    draft_id = (await state.get_data()).get("draft_id")
    try:
        stake = parse_stake(m.text[:32])
    except MoneyError:
        await m.answer(T["bad_stake"])
        return
    try:
        async with transaction(sm) as s:
            d = await betting.set_stake(s, customer.telegram_id, draft_id or "", stake, clock(), cfg)
            q = await s.get(PriceQuote, d.quote_id)
            ev = await s.get(Event, q.event_id)
    except BetError as e:
        await m.answer(err_text(e, cfg))
        if e.code in ("draft_expired", "draft_not_found"):
            await state.clear()
        return
    from app.money import payout_minor, profit_minor
    await m.answer(T["confirm"].format(
        title=fa.match_title(ev.home, ev.away), sel=fa.selection_label(q.market, q.selection, ev.home, ev.away),
        odds=fa.odds(q.odds_milli), stake=fa.money(stake), payout=fa.money(payout_minor(stake, q.odds_milli)),
        profit=fa.money(profit_minor(stake, q.odds_milli))), reply_markup=K.confirm_kb(d.id))


async def confirm(cq, state: FSMContext, sm, settings, bot: Bot, cfg, customer, draft_id: str, now) -> None:
    await state.clear()
    try:
        bet, rc, created = await betting.confirm_bet(sm, settings, draft_id, customer.telegram_id, now)
    except BetError as e:
        await show(cq, err_text(e, cfg), K.home_only())
        return
    except opconfig.ConfigTampered:
        await show(cq, T["err_generic"], K.home_only())
        return
    if not created:       # duplicate tap: show the existing receipt, do not re-pin
        await show(cq, T["placed"], K.kb([[K.b(fa.BTN["mybets"], "mb"), K.b(fa.BTN["home"], "h")]]))
        return
    await show(cq, T["placed"], K.kb([[K.b(fa.BTN["mybets"], "mb"), K.b(fa.BTN["home"], "h")]]))
    status = await deliver_receipt(bot, sm, customer.telegram_id, rc, "open")
    await bot.send_message(customer.telegram_id, T["pin_ok"] if status == "pinned" else T["pin_fail"])


async def on_complaint(m: Message, state: FSMContext, sm: async_sessionmaker, settings: Settings, customer: Customer) -> None:
    text = (m.text or "").strip()[:1000]
    if not text:
        return
    async with transaction(sm) as s:
        c = Complaint(customer_id=customer.telegram_id, text=text)
        s.add(c)
        await s.flush()
        await append_audit(s, settings, f"customer:{customer.telegram_id}", "complaint.created", "complaint", c.id, {})
        cid = c.id
    await state.clear()
    await m.answer(T["complaint_ok"].format(id=fa.digits(str(cid))), reply_markup=K.home_only())


async def fallback(m: Message, state: FSMContext, sm: async_sessionmaker, customer: Customer) -> None:
    async with sm() as s:
        text, kb = await views.home(s, customer)
    await m.answer(text, reply_markup=kb)


def build_router() -> Router:
    """A fresh Router per Dispatcher (a Router can only be attached once)."""
    r = Router()
    r.message.register(start, CommandStart())
    r.message.register(start, Command("menu"))
    r.callback_query.register(on_callback)
    r.message.register(on_stake, Flow.stake, F.text)
    r.message.register(on_complaint, Flow.complaint, F.text)
    r.message.register(fallback)
    return r
