import asyncio
from datetime import timedelta

import pytest
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import func, select, update

from app import compliance
from app.bot.delivery import deliver_receipt
from app.db.models import Bet, Customer, Event, LedgerEntry, PriceQuote, Receipt, SuspendedMarket
from app.db.session import transaction
from app.odds.service import current_quote
from app.services import betting, receipts, wallet
from app.services.betting import BetError
from tests.conftest import bypass_triggers, make_draft, place, register


async def bal(w, cid=111):
    async with w.sm() as s:
        return await wallet.balance(s, cid)


async def test_happy_path_balance_receipt_audit(world):
    await register(world)
    start = await bal(world)
    bet, rc, created = await place(world, stake=2500)
    assert created and await bal(world) == start - 2500
    assert bet.payout_minor == bet.stake_minor * bet.odds_milli // 1000
    async with world.sm() as s:
        r = await s.get(Receipt, bet.id)
        assert receipts.verify(world.settings, r)
        assert r.body["customer_id"] == 111 and r.body["terms_version"] == "1.0"


async def test_incorrect_odds_price_moved_is_rejected(world):
    await register(world)
    did, q = await make_draft(world, 111)
    async with transaction(world.sm) as s:      # the market moves after the customer saw the price
        s.add(PriceQuote(event_id=q.event_id, market=q.market, selection=q.selection, odds_milli=q.odds_milli + 100,
                         best_milli=q.best_milli, median_milli=q.median_milli, n_quotes=5, margin_bp=500,
                         config_version=1, calc={}, created_at=world.clock(),
                         expires_at=world.clock() + timedelta(minutes=10)))
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    assert e.value.code == "price_changed" and e.value.info["odds_milli"] == q.odds_milli + 100
    assert await bal(world) == 100_000       # nothing debited, draft not consumed


async def test_foreign_or_forged_draft_ids_cannot_be_confirmed(world):
    await register(world, 111)
    await register(world, 222)
    did, _ = await make_draft(world, 111)
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 222, world.clock())     # someone else's draft
    assert e.value.code == "draft_not_found"
    with pytest.raises(BetError):
        await betting.confirm_bet(world.sm, world.settings, "ZZZZZZZZZZZZZZZZ", 111, world.clock())


async def test_expired_draft_rejected(world):
    await register(world)
    did, _ = await make_draft(world, 111)
    world.clock.advance(seconds=121)
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    assert e.value.code == "draft_expired" and await bal(world) == 100_000


async def test_expired_prices_cannot_start_a_bet(world):
    await register(world)
    async with world.sm() as s:
        old = await current_quote(s, world.event_id, "1x2", "home", world.clock())
    world.clock.advance(minutes=21)              # beyond price_valid_s=1200
    async with world.sm() as s:
        assert await current_quote(s, world.event_id, "1x2", "home", world.clock()) is None
    async with transaction(world.sm) as s:
        with pytest.raises(BetError) as e:       # a stale quote id replayed from an old callback
            await betting.create_draft(s, 111, old.id, world.clock(), {"bet_cutoff_s": 60, "quote_ttl_s": 120})
    assert e.value.code == "price_unavailable"


async def test_match_already_started_is_rejected(world):
    await register(world)
    did, _ = await make_draft(world, 111)
    async with transaction(world.sm) as s:      # kickoff arrives before the customer confirms
        await s.execute(update(Event).where(Event.id == world.event_id).values(kickoff_utc=world.clock() + timedelta(seconds=30)))
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    assert e.value.code == "event_started" and await bal(world) == 100_000
    async with world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 0


async def test_match_cancelled_is_rejected(world):
    await register(world)
    did, _ = await make_draft(world, 111)
    async with transaction(world.sm) as s:
        await s.execute(update(Event).where(Event.id == world.event_id).values(status="cancelled"))
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    assert e.value.code == "event_not_open"


async def test_api_unavailable_no_new_prices_and_old_ones_age_out(world):
    await register(world)
    world.provider.fail = True
    res = await world.svc.refresh_competition("epl")
    assert res == "provider_unavailable"
    world.clock.advance(minutes=25)
    res = await world.svc.refresh_competition("epl")
    assert res == "provider_unavailable"
    async with world.sm() as s:
        assert await current_quote(s, world.event_id, "1x2", "home", world.clock()) is None


async def test_duplicate_callbacks_create_one_bet(world):
    await register(world)
    did, _ = await make_draft(world, 111, stake=1000)
    b1, r1, c1 = await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    b2, r2, c2 = await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    assert c1 and not c2 and b1.id == b2.id and r1.integrity_hash == r2.integrity_hash
    assert await bal(world) == 99_000
    async with world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 1


async def test_concurrent_confirmations_of_same_draft(world):
    await register(world)
    did, _ = await make_draft(world, 111, stake=1000)
    res = await asyncio.gather(*[betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
                                 for _ in range(8)], return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    assert sum(1 for r in ok if r[2]) == 1, res          # exactly one creator
    assert len({r[0].id for r in ok}) == 1
    assert await bal(world) == 99_000
    async with world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 1


async def test_concurrent_different_bets_cannot_overdraw(world):
    await register(world)
    d1, _ = await make_draft(world, 111, stake=60_000)
    d2, _ = await make_draft(world, 111, selection="away", stake=60_000)
    res = await asyncio.gather(*[betting.confirm_bet(world.sm, world.settings, d, 111, world.clock()) for d in (d1, d2)],
                               return_exceptions=True)
    assert sum(1 for r in res if not isinstance(r, Exception)) == 1
    assert any(isinstance(r, BetError) and r.code == "insufficient_funds" for r in res)
    assert await bal(world) == 40_000


async def test_wallet_never_negative_even_when_called_directly(world):
    await register(world)
    async with world.sm() as s:
        with pytest.raises(wallet.InsufficientFunds):
            await wallet.apply(s, 111, -100_001, "stake", "k-neg")
        await s.rollback()
    assert await bal(world) == 100_000


@pytest.mark.parametrize("stake,code", [(0, "stake_range"), (-5, "stake_range"), (99, "stake_range"),
                                        (100_001, "stake_range"), (200_000_000, "stake_range")])
async def test_invalid_stakes_rejected(world, stake, code):
    await register(world)
    with pytest.raises(BetError) as e:
        await make_draft(world, 111, stake=stake)
    assert e.value.code == code


async def test_insufficient_demo_balance(world):
    await register(world)
    await place(world, stake=100_000)       # spend everything
    with pytest.raises(BetError) as e:
        await make_draft(world, 111, selection="away", stake=100)
    assert e.value.code == "insufficient_funds"


async def test_daily_limit_and_self_exclusion_and_suspension(world):
    await register(world)
    for _ in range(5):
        async with transaction(world.sm) as s:      # top up so only the daily limit can bind
            await wallet.apply(s, 111, 100_000, "demo_grant", f"top{_}")
        await place(world, stake=100_000)
    async with transaction(world.sm) as s:
        await wallet.apply(s, 111, 100_000, "demo_grant", "top-final")
    did, _ = await make_draft(world, 111, stake=100_000)
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 111, world.clock())
    assert e.value.code == "limit"

    await register(world, 222)
    async with transaction(world.sm) as s:
        await compliance.self_exclude(s, 222, 7)
    did, _ = await make_draft(world, 222, stake=100)
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 222, world.clock())
    assert e.value.code == "excluded"

    await register(world, 333)
    did, _ = await make_draft(world, 333, stake=100)
    async with transaction(world.sm) as s:
        s.add(SuspendedMarket(event_id=world.event_id, market="1x2", reason="test", created_by="t"))
    with pytest.raises(BetError) as e:
        await betting.confirm_bet(world.sm, world.settings, did, 333, world.clock())
    assert e.value.code == "suspended"


async def test_self_exclusion_cannot_be_shortened(world):
    await register(world)
    async with transaction(world.sm) as s:
        u1 = await compliance.self_exclude(s, 111, 30)
        u2 = await compliance.self_exclude(s, 111, 1)
        assert u2 == u1


class FakeMsg:
    message_id = 77


class PinFailBot:
    async def send_message(self, **kw):
        return FakeMsg()

    async def pin_chat_message(self, **kw):
        raise TelegramBadRequest(method=None, message="not enough rights to pin a message")


class GoodBot(PinFailBot):
    async def pin_chat_message(self, **kw):
        return True


async def test_pin_failure_keeps_receipt_and_notifies(world):
    await register(world)
    bet, rc, _ = await place(world)
    assert await deliver_receipt(PinFailBot(), world.sm, 111, rc, "open") == "failed"
    async with world.sm() as s:
        r = await s.get(Receipt, bet.id)
        assert r.pin_status == "failed" and r.telegram_message_id == 77 and receipts.verify(world.settings, r)
    assert await deliver_receipt(GoodBot(), world.sm, 111, rc, "open") == "pinned"


async def test_receipt_tampering_is_detected(world):
    await register(world)
    bet, rc, _ = await place(world)
    async with transaction(world.sm) as s:
        await bypass_triggers(s)
        r = await s.get(Receipt, bet.id)
        r.body = {**r.body, "stake_minor": 1}
    async with world.sm() as s:
        assert not receipts.verify(world.settings, await s.get(Receipt, bet.id))


async def test_ledger_sum_matches_wallet(world):
    await register(world)
    await place(world, stake=1234)
    await place(world, selection="away", stake=4321)
    async with world.sm() as s:
        total = (await s.execute(select(func.sum(LedgerEntry.amount_minor)).where(LedgerEntry.customer_id == 111))).scalar()
        assert total == await wallet.balance(s, 111)
