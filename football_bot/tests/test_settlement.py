from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.db.models import AuditEvent, Bet, Claim, Event, EventOutcome, Notification, SecurityEvent, Settlement
from app.db.session import transaction
from app.odds.types import RawResult
from app.results.sources import StaticResultSource
from app.services import claims, settlement, wallet
from app.services.audit import verify_chain
from tests.conftest import place, register


@pytest.mark.parametrize("market,sel,hg,ag,want", [
    ("1x2", "home", 2, 1, "won"), ("1x2", "home", 1, 1, "lost"), ("1x2", "draw", 0, 0, "won"),
    ("1x2", "away", 0, 3, "won"), ("1x2", "away", 3, 0, "lost"),
    ("ou25", "over", 2, 1, "won"), ("ou25", "over", 1, 1, "lost"), ("ou25", "under", 1, 1, "won"),
    ("ou25", "under", 2, 1, "lost"), ("btts", "yes", 1, 1, "won"), ("btts", "yes", 2, 0, "lost"),
    ("btts", "no", 2, 0, "won"), ("btts", "no", 0, 0, "won"), ("btts", "no", 1, 3, "lost"),
])
def test_evaluate_matrix(market, sel, hg, ag, want):
    assert settlement.evaluate(market, sel, "finished", hg, ag) == want


@pytest.mark.parametrize("st", ["postponed", "cancelled", "abandoned"])
def test_evaluate_void_states(st):
    assert settlement.evaluate("1x2", "home", st, None, None) == "void"


def test_evaluate_refuses_unverified_or_bad_scores():
    for args in (("finished", None, 1), ("finished", 1, None), ("finished", -1, 0), ("in_progress", 1, 0)):
        with pytest.raises(ValueError):
            settlement.evaluate("1x2", "home", *args)


async def finish(w, event_id, hg, ag, sources=("src_a", "src_b"), status="finished"):
    """Move the match into the past and feed results from the named sources."""
    async with transaction(w.sm) as s:
        await s.execute(update(Event).where(Event.id == event_id).values(
            kickoff_utc=w.clock() - timedelta(hours=3), status="live"))
        ev = await s.get(Event, event_id)
    res = RawResult(ev.provider_event_id, ev.home, ev.away, ev.kickoff_utc, status, hg, ag)
    srcs = [StaticResultSource(n, [res]) for n in sources]
    await settlement.ingest_results(w.sm, srcs, w.clock())
    return await settlement.decide_outcomes(w.sm, w.settings, w.clock())


async def active(w, bet_id):
    async with w.sm() as s:
        return await s.get(Bet, bet_id)


async def test_two_source_win_settles_and_opens_claim(world):
    await register(world)
    bet, _, _ = await place(world, selection="home", stake=1000)
    assert (await finish(world, world.event_id, 2, 0))["decided"] == 1
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 1
    b = await active(world, bet.id)
    assert b.status == "won"
    async with world.sm() as s:
        c = (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar()
        assert c.status == "pending_request" and c.amount_minor == bet.payout_minor
        assert (await s.execute(select(Notification).where(Notification.kind == "win"))).scalar()
        assert await wallet.balance(s, 111) == 99_000          # stake debited, winnings NOT auto-paid


async def test_duplicate_settlement_is_idempotent(world):
    await register(world)
    bet, _, _ = await place(world, selection="away", stake=1000)
    await finish(world, world.event_id, 0, 1)
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 1
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 0
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 0
    async with world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Settlement))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(Claim))).scalar() == 1
        assert await wallet.balance(s, 111) == 99_000


async def test_incorrect_settlement_losing_bet(world):
    await register(world)
    bet, _, _ = await place(world, selection="home", stake=1000)
    await finish(world, world.event_id, 0, 2)
    await settlement.settle_pending(world.sm, world.settings, world.clock())
    assert (await active(world, bet.id)).status == "lost"
    async with world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Claim))).scalar() == 0


async def test_single_source_never_settles(world):
    await register(world)
    bet, _, _ = await place(world)
    assert (await finish(world, world.event_id, 1, 0, sources=("only_one",)))["decided"] == 0
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 0
    assert (await active(world, bet.id)).status == "open"


async def test_disputed_sources_flag_and_require_admin(world):
    await register(world)
    bet, _, _ = await place(world, selection="home")
    async with transaction(world.sm) as s:
        await s.execute(update(Event).where(Event.id == world.event_id).values(
            kickoff_utc=world.clock() - timedelta(hours=3), status="live"))
        ev = await s.get(Event, world.event_id)
    a = RawResult(ev.provider_event_id, ev.home, ev.away, ev.kickoff_utc, "finished", 2, 0)
    b = RawResult(ev.provider_event_id, ev.home, ev.away, ev.kickoff_utc, "finished", 0, 2)
    await settlement.ingest_results(world.sm, [StaticResultSource("a", [a]), StaticResultSource("b", [b])], world.clock())
    r = await settlement.decide_outcomes(world.sm, world.settings, world.clock())
    assert r == {"decided": 0, "disputed": 1}
    await settlement.decide_outcomes(world.sm, world.settings, world.clock())     # repeat: no duplicate alerts
    async with world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.kind == "result_dispute"))).scalar() == 1
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 0
    async with transaction(world.sm) as s:
        with pytest.raises(settlement.SettlementError):      # reason is mandatory
            await settlement.admin_decide_outcome(s, world.settings, "admin:9001", world.event_id, "finished", 2, 0, " ", world.clock())
        await settlement.admin_decide_outcome(s, world.settings, "admin:9001", world.event_id, "finished", 2, 0,
                                              "checked official league site", world.clock())
    assert await settlement.settle_pending(world.sm, world.settings, world.clock()) == 1
    assert (await active(world, bet.id)).status == "won"


@pytest.mark.parametrize("state", ["cancelled", "postponed", "abandoned"])
async def test_void_states_refund_stake(world, state):
    await register(world)
    bet, _, _ = await place(world, stake=2000)
    await finish(world, world.event_id, None, None, status=state)
    await settlement.settle_pending(world.sm, world.settings, world.clock())
    assert (await active(world, bet.id)).status == "void"
    async with world.sm() as s:
        assert await wallet.balance(s, 111) == 100_000


async def test_correction_reverses_and_preserves_history(world):
    await register(world)
    bet, _, _ = await place(world, selection="home", stake=1000)
    await finish(world, world.event_id, 1, 0)
    await settlement.settle_pending(world.sm, world.settings, world.clock())
    async with transaction(world.sm) as s:      # the customer's claim was already approved & credited
        c = (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar()
        await claims.resolve(s, world.settings, "admin:9001", c.id, True, "ok", world.clock())
        assert await wallet.balance(s, 111) == 99_000 + bet.payout_minor

    with pytest.raises(settlement.SettlementError):
        await settlement.apply_correction(world.sm, world.settings, "admin:9001", world.event_id, "finished", 0, 1, "", world.clock())
    out = await settlement.apply_correction(world.sm, world.settings, "admin:9001", world.event_id, "finished", 0, 1,
                                            "league corrected own-goal attribution", world.clock())
    assert out["bets_changed"] == 1
    assert (await active(world, bet.id)).status == "lost"
    async with world.sm() as s:
        sts = (await s.execute(select(Settlement).order_by(Settlement.id))).scalars().all()
        assert [x.result for x in sts] == ["won", "lost"] and sts[1].supersedes_id == sts[0].id    # history kept
        assert (await s.execute(select(func.count()).select_from(EventOutcome))).scalar() == 2
        assert await wallet.balance(s, 111) == 99_000                                          # credit reversed
        c = (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar()
        assert c.status == "rejected" and c.resolved_by == "correction"
        assert (await s.execute(select(AuditEvent).where(AuditEvent.action == "bet.settlement_corrected"))).scalar()
        ok, bad = await verify_chain(s, world.settings)
        assert ok, bad
    # re-applying the identical correction changes nothing
    again = await settlement.apply_correction(world.sm, world.settings, "admin:9001", world.event_id, "finished", 0, 1,
                                              "repeat", world.clock())
    assert again["bets_changed"] == 0


async def test_admin_cannot_overwrite_existing_outcome_via_decide(world):
    await register(world)
    await place(world)
    await finish(world, world.event_id, 1, 0)
    async with transaction(world.sm) as s:
        with pytest.raises(settlement.SettlementError):
            await settlement.admin_decide_outcome(s, world.settings, "admin:9001", world.event_id, "finished", 5, 5,
                                                  "silent change attempt", world.clock())
