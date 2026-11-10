"""Odds ingestion + price publication + quote lookup. Provider failures never produce guessed prices."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.base import utcnow
from app.db.models import Competition, Event, PriceQuote, SuspendedMarket
from app.odds.normalize import MARKET_SELECTIONS, build_alias_index, norm_name, normalize_event
from app.odds.pricing import price_market
from app.odds.providers.base import OddsProvider
from app.odds.types import ProviderError, RawEvent
from app.services import opconfig
from app.services.audit import append_audit

log = logging.getLogger("odds.service")

COMPETITIONS = [
    ("epl", "soccer_epl", "English Premier League"),
    ("laliga", "soccer_spain_la_liga", "La Liga"),
    ("bundesliga", "soccer_germany_bundesliga", "Bundesliga"),
    ("seriea", "soccer_italy_serie_a", "Serie A"),
    ("ligue1", "soccer_france_ligue_one", "Ligue 1"),
    ("ucl", "soccer_uefa_champs_league", "UEFA Champions League"),
    ("uel", "soccer_uefa_europa_league", "UEFA Europa League"),
    ("uecl", "soccer_uefa_europa_conference_league", "UEFA Conference League"),
]


async def seed_competitions(session: AsyncSession) -> None:
    have = set((await session.execute(select(Competition.key))).scalars())
    for key, pkey, name in COMPETITIONS:
        if key not in have:
            session.add(Competition(key=key, provider_key=pkey, name_en=name))
    await session.flush()


class OddsService:
    def __init__(self, sm: async_sessionmaker[AsyncSession], settings: Settings, primary: OddsProvider,
                 fallback: OddsProvider | None = None, clock: Callable[[], datetime] = utcnow):
        self.sm, self.settings, self.primary, self.fallback, self.clock = sm, settings, primary, fallback, clock

    async def refresh_all(self) -> dict[str, str]:
        async with self.sm() as s:
            comps = (await s.execute(select(Competition).where(Competition.enabled.is_(True)))).scalars().all()
        res = {}
        for c in comps:
            try:
                res[c.key] = await self.refresh_competition(c.key)
            except Exception as e:  # one league failing must not stop the others
                log.error("refresh failed", extra={"competition": c.key, "err": type(e).__name__})
                res[c.key] = f"error:{type(e).__name__}"
        return res

    async def _fetch(self, provider_key: str, now: datetime) -> tuple[str, list[RawEvent]]:
        try:
            return self.primary.name, await self.primary.fetch_events(provider_key, now)
        except ProviderError as e:
            log.warning("primary provider failed", extra={"provider": self.primary.name, "err": str(e)[:120]})
            if not self.fallback:
                raise
            return self.fallback.name, await self.fallback.fetch_events(provider_key, now)

    async def refresh_competition(self, comp_key: str) -> str:
        now = self.clock()
        async with self.sm() as s:
            comp = await s.get(Competition, comp_key)
            provider_key = comp.provider_key
        try:
            provider_name, raw_events = await self._fetch(provider_key, now)
        except ProviderError:
            # No guessed prices: existing quotes simply age out via expires_at.
            return "provider_unavailable"

        async with self.sm() as s:
            try:
                ver, cfg = await opconfig.load_active(s, self.settings)
                alias_idx = build_alias_index(cfg["bookmaker_aliases"])
                n_ok = n_withdrawn = 0
                for rev in raw_events:
                    if rev.commence_utc <= now + timedelta(seconds=cfg["bet_cutoff_s"]):
                        continue
                    ev = await self._upsert_event(s, comp_key, provider_name, rev, now)
                    quotes, rejected = normalize_event(rev, alias_idx, now)
                    for market in MARKET_SELECTIONS:
                        mp = price_market(market, quotes, rejected, cfg, now)
                        if not mp.ok:
                            n_withdrawn += 1
                            await s.execute(update(PriceQuote).where(
                                PriceQuote.event_id == ev.id, PriceQuote.market == market,
                                PriceQuote.expires_at > now).values(expires_at=now))
                            log.info("market withheld", extra={"event": ev.id, "market": market, "why": mp.reason})
                            continue
                        n_ok += 1
                        for sp in mp.selections:
                            s.add(PriceQuote(event_id=ev.id, market=market, selection=sp.selection,
                                             odds_milli=sp.odds_milli, best_milli=sp.best_milli,
                                             median_milli=sp.median_milli, n_quotes=sp.n_quotes,
                                             margin_bp=cfg["margin_bp"], config_version=ver, calc=sp.calc,
                                             created_at=now, expires_at=now + timedelta(seconds=cfg["price_valid_s"])))
                await s.commit()
                return f"ok markets={n_ok} withheld={n_withdrawn}"
            except opconfig.ConfigTampered:
                await s.rollback()
                return "config_tampered"

    async def _upsert_event(self, s: AsyncSession, comp_key: str, provider: str, rev: RawEvent, now: datetime) -> Event:
        ev = (await s.execute(select(Event).where(Event.provider == provider,
                                                  Event.provider_event_id == rev.provider_event_id))).scalar()
        if ev is None:   # cross-provider fixture match (fallback provider): same teams, kickoff within 3h
            cands = (await s.execute(select(Event).where(
                Event.competition_key == comp_key,
                Event.kickoff_utc.between(rev.commence_utc - timedelta(hours=3), rev.commence_utc + timedelta(hours=3))
            ))).scalars().all()
            ev = next((c for c in cands if norm_name(c.home) == norm_name(rev.home)
                       and norm_name(c.away) == norm_name(rev.away)), None)
        if ev is None:
            ev = Event(competition_key=comp_key, provider=provider, provider_event_id=rev.provider_event_id,
                       home=rev.home, away=rev.away, kickoff_utc=rev.commence_utc, status="scheduled", last_seen_at=now)
            s.add(ev)
            await s.flush()
        else:
            ev.last_seen_at = now
            if ev.status == "scheduled" and ev.kickoff_utc != rev.commence_utc:
                await append_audit(s, self.settings, "system", "event.kickoff_changed", "event", ev.id,
                                   {"old": ev.kickoff_utc.isoformat(), "new": rev.commence_utc.isoformat()})
                ev.kickoff_utc = rev.commence_utc
        return ev


# ---- lookups used by the bot / betting engine ------------------------------------------------------
async def is_suspended(s: AsyncSession, event_id: int, market: str) -> bool:
    q = select(SuspendedMarket.id).where(
        SuspendedMarket.lifted_at.is_(None),
        or_(SuspendedMarket.event_id.is_(None), SuspendedMarket.event_id == event_id),
        or_(SuspendedMarket.market.is_(None), SuspendedMarket.market == market)).limit(1)
    return (await s.execute(q)).first() is not None


async def current_quote(s: AsyncSession, event_id: int, market: str, selection: str, now: datetime
                        ) -> PriceQuote | None:
    q = (await s.execute(select(PriceQuote).where(
        PriceQuote.event_id == event_id, PriceQuote.market == market, PriceQuote.selection == selection
    ).order_by(PriceQuote.id.desc()).limit(1))).scalar()
    if q is None or q.expires_at <= now:
        return None
    return q


async def market_view(s: AsyncSession, event_id: int, market: str, now: datetime) -> list[PriceQuote] | None:
    """All selections of a market with currently-valid prices, or None (market unavailable)."""
    if await is_suspended(s, event_id, market):
        return None
    out = []
    for sel in MARKET_SELECTIONS[market]:
        q = await current_quote(s, event_id, market, sel, now)
        if q is None:
            return None
        out.append(q)
    return out


async def bettable_events(s: AsyncSession, comp_key: str, now: datetime, cutoff_s: int) -> list[Event]:
    evs = (await s.execute(select(Event).where(
        Event.competition_key == comp_key, Event.status == "scheduled",
        Event.kickoff_utc > now + timedelta(seconds=cutoff_s)).order_by(Event.kickoff_utc).limit(30))).scalars().all()
    res = []
    for e in evs:
        for m in MARKET_SELECTIONS:
            if await market_view(s, e.id, m, now):
                res.append(e)
                break
    return res


async def mark_started_events(s: AsyncSession, now: datetime) -> int:
    r = await s.execute(update(Event).where(Event.status == "scheduled", Event.kickoff_utc <= now).values(status="live"))
    return r.rowcount or 0
