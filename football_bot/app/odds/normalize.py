"""Normalise untrusted provider payloads into canonical bookmaker/market/selection quotes."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from app.money import MAX_ODDS_MILLI, MIN_ODDS_MILLI, MoneyError, decimal_to_odds_milli
from app.odds.types import NormQuote, RawEvent, Rejected

TARGET_BOOKMAKERS = ("bet365", "pinnacle", "betfair", "bwin", "unibet", "williamhill", "betano", "888sport",
                     "betway", "marathonbet")

_STOP = {"fc", "cf", "afc", "sc", "ac", "as", "ssc", "fk", "sv", "rc", "us", "ud", "cd"}


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in _STOP)


def build_alias_index(aliases: dict[str, list[str]]) -> dict[str, str]:
    idx: dict[str, str] = {}
    for canonical, keys in aliases.items():
        for k in keys:
            idx[k.lower()] = canonical
        idx[canonical.lower()] = canonical
    return idx


def _selection(market: str, outcome_name: str, point: Decimal | None, home: str, away: str) -> str | None:
    n = norm_name(outcome_name)
    if market == "1x2":
        if n == "draw":
            return "draw"
        if n == norm_name(home):
            return "home"
        if n == norm_name(away):
            return "away"
        return None
    if market == "ou25":
        if point != Decimal("2.5"):
            return None
        return {"over": "over", "under": "under"}.get(n)
    if market == "btts":
        return {"yes": "yes", "no": "no"}.get(n)
    return None


_MARKET_MAP = {"h2h": "1x2", "totals": "ou25", "btts": "btts"}


def normalize_event(ev: RawEvent, alias_index: dict[str, str], fetched_at: datetime
                    ) -> tuple[list[NormQuote], list[Rejected]]:
    """Returns accepted quotes and an explicit list of rejected ones (kept for the calc audit trail)."""
    ok: list[NormQuote] = []
    bad: list[Rejected] = []
    for bm in ev.bookmakers:
        canon = alias_index.get(bm.key.lower())
        if canon is None:
            continue  # not one of our mapped bookmakers: ignore silently (not rejected, just unmapped)
        for m in bm.markets:
            market = _MARKET_MAP.get(m.key)
            if market is None:
                continue
            if m.suspended:
                bad.append(Rejected(canon, market, "*", "suspended"))
                continue
            ts = m.last_update or bm.last_update or fetched_at
            for o in m.outcomes:
                sel = _selection(market, o.name, o.point, ev.home, ev.away)
                if sel is None:
                    if market != "ou25":     # other totals lines are expected noise
                        bad.append(Rejected(canon, market, o.name[:40], "unknown_selection"))
                    continue
                if o.price is None:
                    bad.append(Rejected(canon, market, sel, "no_price"))
                    continue
                try:
                    milli = decimal_to_odds_milli(o.price)
                except MoneyError:
                    bad.append(Rejected(canon, market, sel, "invalid_price"))
                    continue
                if not MIN_ODDS_MILLI <= milli <= MAX_ODDS_MILLI:
                    bad.append(Rejected(canon, market, sel, "price_out_of_range"))
                    continue
                ok.append(NormQuote(canon, market, sel, milli, ts, bm.key))
    return ok, bad


MARKET_SELECTIONS = {"1x2": ("home", "draw", "away"), "ou25": ("over", "under"), "btts": ("yes", "no")}
