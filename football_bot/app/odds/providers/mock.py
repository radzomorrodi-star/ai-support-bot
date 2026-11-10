"""Deterministic offline provider for DEMO/dev/tests. Prices are SYNTHETIC - never real bookmaker odds."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

from app.odds.providers.base import OddsProvider
from app.odds.types import RawBookmaker, RawEvent, RawMarket, RawOutcome, RawResult

TEAMS = {
    "soccer_epl": [("Arsenal", "Chelsea"), ("Liverpool", "Manchester City"), ("Tottenham Hotspur", "Newcastle United")],
    "soccer_spain_la_liga": [("Real Madrid", "Barcelona"), ("Atletico Madrid", "Sevilla"), ("Valencia", "Villarreal")],
    "soccer_germany_bundesliga": [("Bayern Munich", "Borussia Dortmund"), ("RB Leipzig", "Bayer Leverkusen"),
                                  ("Eintracht Frankfurt", "VfB Stuttgart")],
    "soccer_italy_serie_a": [("Juventus", "AC Milan"), ("Inter", "Napoli"), ("Roma", "Lazio")],
    "soccer_france_ligue_one": [("Paris Saint Germain", "Marseille"), ("Lyon", "Monaco"), ("Lille", "Nice")],
    "soccer_uefa_champs_league": [("Real Madrid", "Manchester City"), ("Bayern Munich", "Inter"),
                                  ("Paris Saint Germain", "Arsenal")],
    "soccer_uefa_europa_league": [("Roma", "Tottenham Hotspur"), ("Atalanta", "Lyon"), ("Sevilla", "Villarreal")],
    "soccer_uefa_europa_conference_league": [("Fiorentina", "Chelsea"), ("Aston Villa", "Lille"), ("Betis", "Nice")],
}
MOCK_BOOKMAKERS = ["bet365", "pinnacle", "betfair_ex_eu", "bwin", "unibet_eu", "williamhill", "betano", "sport888",
                   "betway", "marathonbet"]


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _odds_from_probs(probs: list[float], overround: float, jitter: float) -> list[Decimal]:
    # synthetic data only: floats are fine here (this is test-fixture generation, not money)
    return [Decimal(str(round(1 / (p * overround * (1 + jitter)), 2))) for p in probs]


class MockOddsProvider(OddsProvider):
    """Fixtures are anchored to UTC day blocks and their ids encode the kickoff, so an event never slides."""
    name = "mock"

    def __init__(self, hours_ahead: tuple[int, ...] = (30, 54, 78), results: dict[str, RawResult] | None = None):
        self.hours_ahead = hours_ahead
        self.results = results or {}
        self.fail = False

    def _fixtures(self, league: str, block: datetime):
        for i, ((home, away), hrs) in enumerate(zip(TEAMS.get(league, []), self.hours_ahead)):
            ko = block + timedelta(hours=hrs)
            yield f"mock-{league}-{i}-{ko:%Y%m%d%H}", home, away, ko

    async def fetch_events(self, league_provider_key: str, now: datetime) -> list[RawEvent]:
        if self.fail:
            from app.odds.types import ProviderError
            raise ProviderError("mock outage")
        block = now.replace(hour=0, minute=0, second=0, microsecond=0)
        out: list[RawEvent] = []
        for eid, home, away, ko in self._fixtures(league_provider_key, block):
            base = _h(eid) % 100
            ph, pd = 0.30 + base / 400, 0.26
            pa = 1 - ph - pd
            pov = 0.52 + (_h(eid, "ou") % 20) / 100
            pyes = 0.50 + (_h(eid, "bt") % 12) / 100
            bms = []
            for bk in MOCK_BOOKMAKERS:
                j = ((_h(eid, bk) % 9) - 4) / 200            # +-2% per bookmaker
                ov = 1.04 + (_h(bk) % 4) / 100
                lu = now - timedelta(seconds=30 + _h(eid, bk, "t") % 120)
                bms.append(RawBookmaker(bk, bk, lu, [
                    RawMarket("h2h", [RawOutcome(n, p) for n, p in
                                      zip([home, "Draw", away], _odds_from_probs([ph, pd, pa], ov, j))], lu),
                    RawMarket("totals", [RawOutcome("Over", _odds_from_probs([pov], ov, j)[0], Decimal("2.5")),
                                         RawOutcome("Under", _odds_from_probs([1 - pov], ov, j)[0], Decimal("2.5"))], lu),
                    RawMarket("btts", [RawOutcome("Yes", _odds_from_probs([pyes], ov, j)[0]),
                                       RawOutcome("No", _odds_from_probs([1 - pyes], ov, j)[0])], lu),
                ]))
            out.append(RawEvent(eid, league_provider_key, home, away, ko, bms))
        return out

    async def fetch_results(self, league_provider_key: str, now: datetime) -> list[RawResult]:
        """DEMO ONLY: deterministic synthetic scores for matches that finished. Not real match data."""
        res = [r for r in self.results.values() if r.provider_event_id.startswith(f"mock-{league_provider_key}")]
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for back in range(0, 5):
            for eid, home, away, ko in self._fixtures(league_provider_key, today - timedelta(days=back)):
                if ko + timedelta(minutes=100) <= now:
                    hg, ag = _h(eid, "hg") % 4, _h(eid, "ag") % 4
                    res.append(RawResult(eid, home, away, ko, "finished", hg, ag, {"synthetic": True}))
        return res
