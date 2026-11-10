"""Settlement engine (demo). Idempotent, auditable, two-source verified, corrections are explicit & append-only.

Rules: regular time (90' + stoppage) only; extra time/penalties are NOT counted.
Void (stake refunded): postponed, cancelled, abandoned.
Unresolved (no settlement, flagged for admin): sources missing/disagree.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import AuditEvent, Bet, Claim, Competition, Event, EventOutcome, EventResult, Settlement
from app.db.session import transaction
from app.odds.normalize import norm_name
from app.odds.types import RawResult
from app.results.sources import ResultSource
from app.security import security_event
from app.services import claims, opconfig, wallet
from app.services.audit import append_audit
from app.services.customers import notify

log = logging.getLogger("settlement")
FINAL = {"finished", "postponed", "cancelled", "abandoned"}


def evaluate(market: str, selection: str, final_status: str, hg: int | None, ag: int | None) -> str:
    if final_status in ("postponed", "cancelled", "abandoned"):
        return "void"
    if final_status != "finished" or hg is None or ag is None or hg < 0 or ag < 0:
        raise ValueError("cannot evaluate without a verified final score")
    if market == "1x2":
        actual = "home" if hg > ag else "away" if ag > hg else "draw"
    elif market == "ou25":
        actual = "over" if hg + ag >= 3 else "under"
    elif market == "btts":
        actual = "yes" if hg > 0 and ag > 0 else "no"
    else:
        raise ValueError("unknown market")
    return "won" if actual == selection else "lost"


def _match(ev: Event, r: RawResult) -> bool:
    if r.provider_event_id == ev.provider_event_id:
        return True
    if norm_name(r.home) != norm_name(ev.home) or norm_name(r.away) != norm_name(ev.away):
        return False
    return r.commence_utc is None or abs(r.commence_utc - ev.kickoff_utc) <= timedelta(hours=6)


async def ingest_results(sm: async_sessionmaker[AsyncSession], sources: list[ResultSource], now: datetime) -> int:
    """Pull completed results from every source and store them (append-only, de-duplicated)."""
    added = 0
    async with sm() as s:
        evs = (await s.execute(select(Event).where(Event.status.in_(("scheduled", "live")),
                                                   Event.kickoff_utc <= now - timedelta(minutes=100)))).scalars().all()
        comps = {c.key: c.provider_key for c in (await s.execute(select(Competition))).scalars()}
        by_comp: dict[str, list[Event]] = {}
        for e in evs:
            by_comp.setdefault(e.competition_key, []).append(e)
        for comp_key, events in by_comp.items():
            for src in sources:
                try:
                    results = await src.fetch(comps[comp_key], now)
                except Exception as e:
                    log.warning("result source failed", extra={"source": src.name, "err": type(e).__name__})
                    continue
                for r in results:
                    if r.final_status not in FINAL:
                        continue
                    for ev in events:
                        if not _match(ev, r):
                            continue
                        dup = (await s.execute(select(EventResult.id).where(
                            EventResult.event_id == ev.id, EventResult.source == src.name,
                            EventResult.final_status == r.final_status, EventResult.home_goals == r.home_goals,
                            EventResult.away_goals == r.away_goals))).first()
                        if not dup:
                            s.add(EventResult(event_id=ev.id, source=src.name, final_status=r.final_status,
                                              home_goals=r.home_goals, away_goals=r.away_goals, fetched_at=now,
                                              raw=r.raw))
                            added += 1
        await s.commit()
    return added


async def _active_outcome(s: AsyncSession, event_id: int) -> EventOutcome | None:
    return (await s.execute(select(EventOutcome).where(EventOutcome.event_id == event_id)
                            .order_by(EventOutcome.id.desc()).limit(1))).scalar()


async def decide_outcomes(sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime) -> dict[str, int]:
    decided = disputed = 0
    async with transaction(sm) as s:
        evs = (await s.execute(select(Event).where(Event.status.in_(("scheduled", "live"))))).scalars().all()
        for ev in evs:
            if await _active_outcome(s, ev.id):
                continue
            rows = (await s.execute(select(EventResult).where(EventResult.event_id == ev.id)
                                    .order_by(EventResult.id.desc()))).scalars().all()
            latest: dict[str, EventResult] = {}
            for r in rows:
                latest.setdefault(r.source, r)
            if len(latest) < 2:
                continue
            verdicts = {(r.final_status, r.home_goals, r.away_goals) for r in latest.values()}
            if len(verdicts) == 1:
                fs, hg, ag = next(iter(verdicts))
                s.add(EventOutcome(event_id=ev.id, final_status=fs, home_goals=hg, away_goals=ag,
                                   decided_by="system:2-source", sources=sorted(latest), created_at=now))
                ev.status = fs
                await s.flush()
                await append_audit(s, settings, "system", "outcome.decided", "event", ev.id,
                                   {"final_status": fs, "score": [hg, ag], "sources": sorted(latest)})
                decided += 1
            else:
                disputed += 1
                seen = (await s.execute(select(AuditEvent.id).where(
                    AuditEvent.action == "result.dispute", AuditEvent.entity_id == str(ev.id)))).first()
                if not seen:
                    await append_audit(s, settings, "system", "result.dispute", "event", ev.id,
                                       {"verdicts": {k: [v.final_status, v.home_goals, v.away_goals]
                                                     for k, v in latest.items()}})
                    await security_event(s, "result_dispute", "high", event_id=ev.id)
    return {"decided": decided, "disputed": disputed}


async def _effect_won(s, settings, cfg, bet, now):
    await claims.create_for_win(s, settings, cfg, bet, now)


async def _undo(s: AsyncSession, settings: Settings, prev: Settlement, bet: Bet, new_id: int, now: datetime) -> None:
    if prev.result == "won":
        c = (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar()
        if c:
            if c.status == "approved":
                await wallet.apply(s, bet.customer_id, -c.amount_minor, "correction", f"undo-claim:{c.id}:{new_id}",
                                   "claim", str(c.id), allow_partial=True)
            c.status, c.resolved_by, c.resolved_at = "rejected", "correction", now
    elif prev.result == "void":
        await wallet.apply(s, bet.customer_id, -bet.stake_minor, "correction", f"undo-refund:{bet.id}:{new_id}",
                           "bet", bet.id, allow_partial=True)


async def _settle_bet(s: AsyncSession, settings: Settings, cfg: dict, bet: Bet, ev: Event, outcome: EventOutcome,
                      prev: Settlement | None, decided_by: str, reason: str | None, now: datetime) -> bool:
    result = evaluate(bet.market, bet.selection, outcome.final_status, outcome.home_goals, outcome.away_goals)
    if prev is not None and prev.result == result:
        return False
    payout = bet.payout_minor if result == "won" else bet.stake_minor if result == "void" else 0
    st = Settlement(bet_id=bet.id, outcome_id=outcome.id, result=result, payout_minor=payout,
                    supersedes_id=prev.id if prev else None, decided_by=decided_by, reason=reason, created_at=now)
    s.add(st)
    await s.flush()
    if prev:
        await _undo(s, settings, prev, bet, st.id, now)
    if result == "won":
        await _effect_won(s, settings, cfg, bet, now)
    elif result == "void":
        await wallet.apply(s, bet.customer_id, bet.stake_minor, "refund", f"refund:{bet.id}:{st.id}", "bet", bet.id)
        await notify(s, bet.customer_id, "void", {"bet_id": bet.id, "amount_minor": bet.stake_minor},
                     f"void:{bet.id}:{st.id}")
    else:
        await notify(s, bet.customer_id, "loss", {"bet_id": bet.id}, f"loss:{bet.id}:{st.id}")
    bet.status, bet.settled_at = result, now
    await append_audit(s, settings, decided_by, "bet.settled" if not prev else "bet.settlement_corrected", "bet",
                       bet.id, {"result": result, "outcome_id": outcome.id, "payout_minor": payout,
                                "supersedes": prev.id if prev else None, "reason": reason})
    return True


async def settle_pending(sm: async_sessionmaker[AsyncSession], settings: Settings, now: datetime) -> int:
    """Settle every open bet whose event has a verified outcome. Safe to run repeatedly / concurrently."""
    n = 0
    async with sm() as s:
        ids = (await s.execute(select(Event.id).where(Event.id.in_(
            select(Bet.event_id).where(Bet.status == "open"))))).scalars().all()
    for eid in ids:
        async with transaction(sm) as s:
            outcome = await _active_outcome(s, eid)
            if outcome is None:
                continue
            _, cfg = await opconfig.load_active(s, settings)
            ev = await s.get(Event, eid)
            bets = (await s.execute(select(Bet).where(Bet.event_id == eid, Bet.status == "open"))).scalars().all()
            for b in bets:
                if await _settle_bet(s, settings, cfg, b, ev, outcome, None, outcome.decided_by, None, now):
                    n += 1
    return n


class SettlementError(Exception):
    pass


async def admin_decide_outcome(s: AsyncSession, settings: Settings, admin_actor: str, event_id: int,
                               final_status: str, hg: int | None, ag: int | None, reason: str, now: datetime
                               ) -> EventOutcome:
    """Explicit admin decision for an event that has NO outcome yet (e.g. unresolved/disputed)."""
    if await _active_outcome(s, event_id):
        raise SettlementError("outcome already exists; use correction")
    return await _write_outcome(s, settings, admin_actor, event_id, final_status, hg, ag, reason, None, now)


async def _write_outcome(s, settings, actor, event_id, final_status, hg, ag, reason, supersedes, now) -> EventOutcome:
    if final_status not in FINAL:
        raise SettlementError("invalid final status")
    if final_status == "finished" and (hg is None or ag is None or hg < 0 or ag < 0):
        raise SettlementError("finished requires a score")
    if not reason or not reason.strip():
        raise SettlementError("reason required")
    if final_status != "finished":
        hg = ag = None
    o = EventOutcome(event_id=event_id, final_status=final_status, home_goals=hg, away_goals=ag,
                     decided_by=actor, sources=["admin"], supersedes_id=supersedes, reason=reason[:300], created_at=now)
    s.add(o)
    ev = await s.get(Event, event_id)
    ev.status = final_status
    await s.flush()
    await append_audit(s, settings, actor, "outcome.admin_decided" if supersedes is None else "outcome.corrected",
                       "event", event_id, {"final_status": final_status, "score": [hg, ag], "reason": reason[:300],
                                           "supersedes": supersedes})
    return o


async def apply_correction(sm: async_sessionmaker[AsyncSession], settings: Settings, admin_actor: str, event_id: int,
                           final_status: str, hg: int | None, ag: int | None, reason: str, now: datetime) -> dict:
    """Correct a finalised outcome: new superseding rows + financial reversals. Never edits history."""
    async with transaction(sm) as s:
        prev_outcome = await _active_outcome(s, event_id)
        if prev_outcome is None:
            raise SettlementError("no outcome to correct")
        o = await _write_outcome(s, settings, admin_actor, event_id, final_status, hg, ag, reason,
                                 prev_outcome.id, now)
        _, cfg = await opconfig.load_active(s, settings)
        ev = await s.get(Event, event_id)
        changed = 0
        for b in (await s.execute(select(Bet).where(Bet.event_id == event_id))).scalars().all():
            prev = (await s.execute(select(Settlement).where(Settlement.bet_id == b.id)
                                    .order_by(Settlement.id.desc()).limit(1))).scalar()
            if await _settle_bet(s, settings, cfg, b, ev, o, prev, admin_actor, reason, now):
                changed += 1
        return {"outcome_id": o.id, "bets_changed": changed}
