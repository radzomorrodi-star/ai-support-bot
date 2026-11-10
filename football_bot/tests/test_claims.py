from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import Claim, Notification
from app.db.session import transaction
from app.services import claims, opconfig, settlement, wallet
from tests.conftest import place, register
from tests.test_settlement import finish


async def won_claim(world):
    await register(world)
    bet, _, _ = await place(world, selection="home", stake=1000)
    await finish(world, world.event_id, 3, 0)
    await settlement.settle_pending(world.sm, world.settings, world.clock())
    async with world.sm() as s:
        _, cfg = await opconfig.load_active(s, world.settings)
        return bet, (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar(), cfg


async def kinds(world):
    async with world.sm() as s:
        return [n.kind for n in (await s.execute(select(Notification).order_by(Notification.id))).scalars()]


async def test_ten_day_deadline_reminders_and_admin_review_not_forfeit(world):
    bet, c, cfg = await won_claim(world)
    t0 = world.clock()
    assert c.deadline_at == t0 + timedelta(days=10) and c.status == "pending_request"
    assert "win" in await kinds(world)

    world.clock.advance(days=5)
    assert (await claims.sweep(world.sm, world.settings, cfg, world.clock()))["reminded"] == 0
    world.clock.advance(days=2, hours=1)                                  # 3 days left
    assert (await claims.sweep(world.sm, world.settings, cfg, world.clock()))["reminded"] == 1
    assert (await claims.sweep(world.sm, world.settings, cfg, world.clock()))["reminded"] == 0     # not repeated
    world.clock.advance(days=2)                                           # 1 day left
    assert (await claims.sweep(world.sm, world.settings, cfg, world.clock()))["reminded"] == 1
    world.clock.advance(days=1, hours=2)                                  # deadline passed
    r = await claims.sweep(world.sm, world.settings, cfg, world.clock())
    assert r["flagged"] == 1
    async with world.sm() as s:
        c = (await s.execute(select(Claim))).scalar()
        assert c.status == "admin_review"                  # NOT forfeited / extinguished
        assert c.amount_minor == bet.payout_minor
    assert (await kinds(world)).count("claim_reminder") == 2 and "claim_review" in await kinds(world)
    # original win & settlement records are untouched
    async with world.sm() as s:
        from app.db.models import Bet
        assert (await s.get(Bet, bet.id)).status == "won"


async def test_late_request_still_possible_and_flagged(world):
    bet, c, cfg = await won_claim(world)
    world.clock.advance(days=11)
    await claims.sweep(world.sm, world.settings, cfg, world.clock())
    got = await claims.request_claim(world.sm, world.settings, 111, bet.id, world.clock())
    assert got.status == "requested" and got.late_request is True


async def test_duplicate_and_foreign_requests_blocked(world):
    bet, c, cfg = await won_claim(world)
    await claims.request_claim(world.sm, world.settings, 111, bet.id, world.clock())
    with pytest.raises(claims.ClaimDuplicate):
        await claims.request_claim(world.sm, world.settings, 111, bet.id, world.clock())
    await register(world, 222)
    with pytest.raises(claims.ClaimNotFound):
        await claims.request_claim(world.sm, world.settings, 222, bet.id, world.clock())


async def test_admin_resolution_credits_once(world):
    bet, c, cfg = await won_claim(world)
    await claims.request_claim(world.sm, world.settings, 111, bet.id, world.clock())
    async with transaction(world.sm) as s:
        with pytest.raises(claims.ClaimError):
            await claims.resolve(s, world.settings, "admin:9001", c.id, True, "", world.clock())
    async with transaction(world.sm) as s:
        await claims.resolve(s, world.settings, "admin:9001", c.id, True, "verified", world.clock())
    async with transaction(world.sm) as s:
        with pytest.raises(claims.ClaimError):
            await claims.resolve(s, world.settings, "admin:9001", c.id, True, "again", world.clock())
        assert await wallet.balance(s, 111) == 99_000 + bet.payout_minor
