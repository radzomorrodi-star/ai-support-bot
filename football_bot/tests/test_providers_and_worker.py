import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.bot.notifier import drain
from app.db.models import ApiUsage, Bet, Claim, Customer, Event, Notification
from app.db.session import transaction
from app.odds.providers.theoddsapi import TheOddsApiProvider
from app.odds.service import OddsService
from app.odds.types import ProviderError, ProviderRateLimited
from app.results.sources import ProviderResultSource
from app.odds.providers.mock import MockOddsProvider
from app.services import betting, claims, opconfig, settlement, wallet
from tests.conftest import Clock, make_draft, place, register
from tests.fakebot import make_bot

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def odds_payload(ko="2026-11-12T15:00:00Z"):
    def bm(key, h, d, a):
        return {"key": key, "title": key, "last_update": "2026-11-10T11:59:00Z", "markets": [
            {"key": "h2h", "last_update": "2026-11-10T11:59:00Z", "outcomes": [
                {"name": "Arsenal", "price": h}, {"name": "Chelsea", "price": a}, {"name": "Draw", "price": d}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5}, {"name": "Under", "price": 1.95, "point": 2.5},
                                           {"name": "Over", "price": 1.3, "point": 1.5}]}]}
    return [{"id": "ev1", "sport_key": "soccer_epl", "commence_time": ko, "home_team": "Arsenal", "away_team": "Chelsea",
             "bookmakers": [bm("pinnacle", 2.0, 3.5, 3.9), bm("unibet_eu", 1.95, 3.4, 3.8), bm("williamhill", 2.05, 3.3, 3.9),
                            {"key": "broken", "markets": "garbage"}, "junk", None]}, {"id": 5}, "x", {"id": "bad", "commence_time": "nope"}]


def provider(handler, sm=None, btts=False):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.the-odds-api.com/v4")
    return TheOddsApiProvider("SECRETKEY123", "eu,uk", 5, sm, fetch_btts=btts, client=client)


async def test_theoddsapi_parses_defensively_and_records_quota(sm):
    seen = {}

    def handler(req: httpx.Request):
        seen["params"], seen["path"] = dict(req.url.params), req.url.path
        return httpx.Response(200, json=odds_payload(), headers={"x-requests-remaining": "480", "x-requests-used": "20"})

    evs = await provider(handler, sm).fetch_events("soccer_epl", NOW)
    assert seen["path"] == "/v4/sports/soccer_epl/odds" and seen["params"]["oddsFormat"] == "decimal"
    assert seen["params"]["markets"] == "h2h,totals" and seen["params"]["regions"] == "eu,uk"
    assert len(evs) == 1 and {b.key for b in evs[0].bookmakers} == {"pinnacle", "unibet_eu", "williamhill"}
    async with sm() as s:
        u = (await s.execute(select(ApiUsage))).scalar()
        assert u.ok and u.quota_remaining == 480 and u.quota_used == 20
        assert "SECRETKEY123" not in json.dumps([u.endpoint, u.error])


async def test_theoddsapi_drops_started_events_and_handles_failures(sm):
    started = provider(lambda r: httpx.Response(200, json=odds_payload("2026-11-10T11:00:00Z")))
    assert await started.fetch_events("soccer_epl", NOW) == []
    with pytest.raises(ProviderRateLimited):
        await provider(lambda r: httpx.Response(429), sm).fetch_events("soccer_epl", NOW)
    with pytest.raises(ProviderError) as e:
        await provider(lambda r: httpx.Response(401, text="bad key SECRETKEY123"), sm).fetch_events("soccer_epl", NOW)
    assert "SECRETKEY123" not in str(e.value)
    with pytest.raises(ProviderError):
        await provider(lambda r: httpx.Response(200, text="<html>"), sm).fetch_events("soccer_epl", NOW)
    with pytest.raises(ProviderError):
        await provider(lambda r: httpx.Response(200, json={"not": "a list"}), sm).fetch_events("soccer_epl", NOW)

    def boom(req):
        raise httpx.ConnectTimeout("t/o")
    with pytest.raises(ProviderError):
        await provider(boom, sm).fetch_events("soccer_epl", NOW)
    async with sm() as s:
        assert (await s.execute(select(func.count()).select_from(ApiUsage).where(ApiUsage.ok.is_(False)))).scalar() == 5


async def test_theoddsapi_scores_only_completed_with_parseable_scores():
    payload = [
        {"id": "a", "completed": True, "home_team": "Arsenal", "away_team": "Chelsea", "commence_time": "2026-11-09T15:00:00Z",
         "scores": [{"name": "Arsenal", "score": "2"}, {"name": "Chelsea", "score": "1"}]},
        {"id": "b", "completed": False, "home_team": "X", "away_team": "Y", "scores": None},
        {"id": "c", "completed": True, "home_team": "X", "away_team": "Y", "scores": [{"name": "X", "score": "abc"}]},
        {"id": "d", "completed": True, "home_team": "X", "away_team": "Y", "scores": None}]
    res = await provider(lambda r: httpx.Response(200, json=payload)).fetch_results("soccer_epl", NOW)
    assert [(r.provider_event_id, r.home_goals, r.away_goals) for r in res] == [("a", 2, 1)]


async def test_provider_failure_falls_back_to_secondary_without_duplicate_events(sm, settings):
    clock = Clock(NOW)
    primary = MockOddsProvider()
    secondary = MockOddsProvider()
    secondary.name = "backup"
    svc = OddsService(sm, settings, primary, secondary, clock=clock)
    assert (await svc.refresh_competition("epl")).startswith("ok")
    primary.fail = True
    assert (await svc.refresh_competition("epl")).startswith("ok")        # served by the fallback
    async with sm() as s:
        n_events = (await s.execute(select(func.count()).select_from(Event))).scalar()
        assert n_events == 3          # same fixtures matched across providers (teams + kickoff), not duplicated


async def test_automated_demo_cycle_with_mock_sources(world):
    """refresh -> bet -> kickoff passes -> 2 sources agree -> settle -> claim + notification, no manual step."""
    await register(world)
    bet, _, _ = await place(world, selection="home", stake=1000)
    async with world.sm() as s:
        ev = await s.get(Event, bet.event_id)
    world.clock.t = ev.kickoff_utc + timedelta(hours=3)
    srcs = [ProviderResultSource(world.provider, "mock_a"), ProviderResultSource(world.provider, "mock_b")]
    from app.odds.service import mark_started_events
    async with transaction(world.sm) as s:
        await mark_started_events(s, world.clock())
    assert await settlement.ingest_results(world.sm, srcs, world.clock()) >= 2
    assert (await settlement.decide_outcomes(world.sm, world.settings, world.clock()))["decided"] >= 1
    await settlement.settle_pending(world.sm, world.settings, world.clock())
    async with world.sm() as s:
        b = await s.get(Bet, bet.id)
        assert b.status in ("won", "lost")
        if b.status == "won":
            assert (await s.execute(select(Claim))).scalar().status == "pending_request"


async def test_notifier_delivers_persian_win_notice_with_claim_button(world):
    await register(world)
    bet, _, _ = await place(world, selection="home")
    from tests.test_settlement import finish
    await finish(world, world.event_id, 4, 0)
    await settlement.settle_pending(world.sm, world.settings, world.clock())
    bot, sess = make_bot()
    assert await drain(bot, world.sm) == 1
    text = sess.of("SendMessage")[0]["text"]
    assert "شرط شما برنده شد" in text and bet.id in text and "مهلت درخواست" in text
    assert any(b.get("callback_data", "").startswith("cl:") for row in sess.last_markup() for b in row)
    assert await drain(bot, world.sm) == 0                      # not re-sent


async def test_concurrent_bets_cannot_exceed_daily_limit(world):
    import asyncio
    await register(world)
    async with transaction(world.sm) as s:
        await wallet.apply(s, 111, 2_000_000, "demo_grant", "big")
    drafts = [(await make_draft(world, 111, selection="home" if i % 2 else "away", stake=100_000))[0] for i in range(9)]
    res = await asyncio.gather(*[betting.confirm_bet(world.sm, world.settings, d, 111, world.clock()) for d in drafts],
                               return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    assert len(ok) == 5, res                                    # default daily limit 5,000.00 = 5 x 1,000.00
    assert all(isinstance(r, betting.BetError) and r.code == "limit" for r in res if isinstance(r, Exception))
