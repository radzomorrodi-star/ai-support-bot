from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.money import MoneyError, parse_stake, payout_minor, profit_minor
from app.odds.normalize import build_alias_index, normalize_event
from app.odds.pricing import price_market
from app.odds.types import NormQuote, RawBookmaker, RawEvent, RawMarket, RawOutcome
from app.services.opconfig import DEFAULT_CONFIG

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
CFG = dict(DEFAULT_CONFIG)


def nq(bm, sel, odds, age=60, market="1x2"):
    return NormQuote(bm, market, sel, odds, NOW - timedelta(seconds=age), bm)


def book(bm, h, d, a, age=60):
    return [nq(bm, "home", h, age), nq(bm, "draw", d, age), nq(bm, "away", a, age)]


def quotes5():
    q = []
    for bm, (h, d, a) in {"pinnacle": (2000, 3500, 3900), "bet365": (1950, 3400, 3800), "betfair": (2050, 3450, 3950),
                          "unibet": (1900, 3300, 3700), "bwin": (1980, 3350, 3850)}.items():
        q += book(bm, h, d, a)
    return q


@pytest.mark.parametrize("bad", ["", "abc", "-5", "0", "0.00", "1e3", "1.234", "99999999", "1,2,3", " ", "NaN", "10 ; DROP"])
def test_parse_stake_rejects_garbage(bad):
    with pytest.raises(MoneyError):
        parse_stake(bad)


def test_parse_stake_accepts_persian_digits_and_exact_minor_units():
    assert parse_stake("۲۵٫۵۰") == 2550
    assert parse_stake("10") == 1000
    assert parse_stake("0.1") == 10


def test_payout_uses_integer_math_and_rounds_down():
    assert payout_minor(333, 1850) == 616            # 616.05 -> floor
    assert profit_minor(1000, 2000) == 1000
    with pytest.raises(MoneyError):
        payout_minor(0, 2000)


def test_best_median_margin_and_overround():
    mp = price_market("1x2", quotes5(), [], CFG, NOW)
    assert mp.ok
    home = next(s for s in mp.selections if s.selection == "home")
    assert home.best_milli == 2050 and home.median_milli == 1980 and home.n_quotes == 5
    for sp in mp.selections:
        assert sp.odds_milli <= sp.best_milli            # never better than the best real quote
        assert sp.odds_milli % 10 == 0                   # 2-decimal prices
        assert len(sp.calc["quotes"]) == 5 and sp.calc["margin_bp"] == CFG["margin_bp"]
        assert "last_update" in sp.calc["quotes"][0]     # source timestamps stored
    assert CFG["cust_overround_min_bp"] <= mp.summary["customer_overround_bp"] <= CFG["cust_overround_max_bp"]
    # margin is applied to DE-VIGGED fair probabilities: customer overround ~= 10000 + margin_bp
    # (+ a little from flooring/capping), independent of how fat the bookmakers' own margins are.
    assert 10000 + CFG["margin_bp"] - 1 <= mp.summary["customer_overround_bp"] <= 10000 + CFG["margin_bp"] + 150


def test_margin_is_configurable_and_monotonic():
    lo = price_market("1x2", quotes5(), [], {**CFG, "margin_bp": 200}, NOW)
    hi = price_market("1x2", quotes5(), [], {**CFG, "margin_bp": 800}, NOW)
    assert all(a.odds_milli >= b.odds_milli for a, b in zip(lo.selections, hi.selections))
    assert hi.summary["customer_overround_bp"] > lo.summary["customer_overround_bp"]


def test_stale_quotes_are_excluded_and_reported():
    q = quotes5() + book("williamhill", 2500, 3500, 3900, age=99999)
    mp = price_market("1x2", q, [], CFG, NOW)
    assert mp.ok and all(s.n_quotes == 5 for s in mp.selections)
    assert any(e["bookmaker"] == "williamhill" and e["reason"].startswith("stale")
               for e in mp.selections[0].calc["excluded"])


def test_too_few_valid_quotes_withholds_market():
    q = [x for x in quotes5() if x.bookmaker in ("pinnacle", "bet365")]
    mp = price_market("1x2", q, [], CFG, NOW)
    assert not mp.ok and mp.reason.startswith("insufficient_quotes")


def test_future_timestamps_untrusted():
    q = [x for x in quotes5() if x.bookmaker in ("pinnacle", "bet365", "betfair")] + book("unibet", 1900, 3300, 3700, age=-9000)
    mp = price_market("1x2", q, [], CFG, NOW)
    assert mp.ok and mp.selections[0].n_quotes == 3


def test_implausible_market_overround_withheld():
    q = []
    for bm in ("pinnacle", "bet365", "betfair"):
        q += book(bm, 3000, 4000, 5000)       # sum of implied probs ~0.78 -> arbitrage-like garbage data
    mp = price_market("1x2", q, [], CFG, NOW)
    assert not mp.ok and "overround" in mp.reason


def test_normalize_drops_invalid_and_unmapped_bookmakers():
    idx = build_alias_index(CFG["bookmaker_aliases"])
    mk = lambda *p: RawMarket("h2h", [RawOutcome("Arsenal", p[0]), RawOutcome("Draw", p[1]), RawOutcome("Chelsea", p[2])], NOW)
    ev = RawEvent("e1", "soccer_epl", "Arsenal", "Chelsea", NOW + timedelta(days=1), [
        RawBookmaker("pinnacle", "Pinnacle", NOW, [mk(Decimal("0.5"), Decimal("3.4"), Decimal("4.1"))]),     # <1.01
        RawBookmaker("betfair_ex_eu", "Betfair", NOW, [mk(Decimal("1.85"), None, Decimal("4.1"))]),            # missing price
        RawBookmaker("some_random_book", "X", NOW, [mk(Decimal("1.9"), Decimal("3.4"), Decimal("4.1"))]),     # unmapped
        RawBookmaker("williamhill", "WH", NOW, [mk(Decimal("1.85"), Decimal("3.4"), Decimal("4.1"))]),
    ])
    ok, bad = normalize_event(ev, idx, NOW)
    got = {(q.bookmaker, q.selection) for q in ok}
    assert ("pinnacle", "home") not in got and ("betfair", "draw") not in got        # invalid outcomes dropped
    assert {("pinnacle", "draw"), ("pinnacle", "away"), ("betfair", "home"), ("williamhill", "home")} <= got
    assert {r.reason for r in bad} >= {"price_out_of_range", "no_price"}
    assert all(q.bookmaker != "some_random_book" for q in ok)
