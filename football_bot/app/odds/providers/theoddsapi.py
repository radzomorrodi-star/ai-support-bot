"""The Odds API v4 adapter (https://the-odds-api.com/liveapi/guides/v4/).

Verified from the official guide: regions (us, us2, uk, au, eu), `oddsFormat=decimal`,
`/sports/{sport}/odds`, `/sports/{sport}/scores`, quota cost = markets x regions for odds.
NOT verified (check the live docs / your plan before relying on them): the exact bookmaker keys per
region, availability of all ten target bookmakers, BTTS availability per sport, numeric rate limits.
The `scores` endpoint is a data feed, not an "official" league source; see docs/ODDS_PROVIDERS.md.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ApiUsage
from app.odds.providers.base import OddsProvider
from app.odds.types import (ProviderError, ProviderRateLimited, RawBookmaker, RawEvent, RawMarket, RawOutcome,
                            RawResult)

log = logging.getLogger("odds.theoddsapi")
BASE = "https://api.the-odds-api.com/v4"


def _dt(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _dec(v: Any) -> Decimal | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def parse_event(e: Any) -> RawEvent | None:
    """Defensive parser: any malformed element is dropped, never trusted."""
    if not isinstance(e, dict):
        return None
    ct = _dt(e.get("commence_time"))
    if not (ct and isinstance(e.get("id"), str) and isinstance(e.get("home_team"), str)
            and isinstance(e.get("away_team"), str)):
        return None
    bms: list[RawBookmaker] = []
    books = e.get("bookmakers")
    for b in books if isinstance(books, list) else []:
        if not isinstance(b, dict) or not isinstance(b.get("key"), str) or not isinstance(b.get("markets"), list):
            continue
        mkts: list[RawMarket] = []
        for m in b["markets"]:
            if not isinstance(m, dict) or not isinstance(m.get("key"), str) or not isinstance(m.get("outcomes"), list):
                continue
            outs = [RawOutcome(str(o.get("name", ""))[:80], _dec(o.get("price")), _dec(o.get("point")))
                    for o in m["outcomes"] if isinstance(o, dict)]
            mkts.append(RawMarket(m["key"], outs, _dt(m.get("last_update"))))
        if not mkts:
            continue
        bms.append(RawBookmaker(b["key"], str(b.get("title", ""))[:60], _dt(b.get("last_update")), mkts))
    return RawEvent(e["id"], str(e.get("sport_key", "")), e["home_team"][:96], e["away_team"][:96], ct, bms)


class TheOddsApiProvider(OddsProvider):
    name = "the_odds_api"

    def __init__(self, api_key: str, regions: str, timeout: float, sm: async_sessionmaker[AsyncSession] | None = None,
                 fetch_btts: bool = True, client: httpx.AsyncClient | None = None):
        self._key, self._regions, self._sm, self._fetch_btts = api_key, regions, sm, fetch_btts
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout), base_url=BASE)

    async def _get(self, path: str, params: dict, expect: type = list) -> Any:
        """GET + validate the payload shape. The usage row's `ok` means "returned a usable payload"."""
        t0 = time.monotonic()
        status, remaining, used, err, ok = None, None, None, None, False
        try:
            r = await self._client.get(path, params={**params, "apiKey": self._key})
            status = r.status_code
            remaining = int(r.headers["x-requests-remaining"]) if "x-requests-remaining" in r.headers else None
            used = int(r.headers["x-requests-used"]) if "x-requests-used" in r.headers else None
            if r.status_code == 429:
                raise ProviderRateLimited("429 from provider")
            if r.status_code >= 400:
                raise ProviderError(f"http {r.status_code}")      # body deliberately not logged (may echo key)
            data = r.json()
            if not isinstance(data, expect):
                raise ProviderError("unexpected payload shape")
            ok = True
            return data
        except httpx.HTTPError as e:
            err = type(e).__name__
            raise ProviderError(f"transport error: {err}") from e
        except ValueError as e:
            err = "bad_json"
            raise ProviderError("invalid JSON") from e
        except ProviderError as e:
            err = str(e)[:100]
            raise
        finally:
            await self._record(path.split("/")[-1], status, ok, remaining, used,
                               int((time.monotonic() - t0) * 1000), err)

    async def _record(self, endpoint, status, ok, remaining, used, latency, err):
        if not self._sm:
            return
        async with self._sm() as s:
            s.add(ApiUsage(provider=self.name, endpoint=endpoint, http_status=status, ok=ok, quota_remaining=remaining,
                           quota_used=used, latency_ms=latency, error=err))
            await s.commit()

    async def fetch_events(self, league_provider_key: str, now: datetime) -> list[RawEvent]:
        data = await self._get(f"/sports/{league_provider_key}/odds",
                               {"regions": self._regions, "markets": "h2h,totals", "oddsFormat": "decimal",
                                "dateFormat": "iso"})
        if not isinstance(data, list):
            raise ProviderError("unexpected payload shape")
        events = [ev for ev in (parse_event(e) for e in data) if ev and ev.commence_utc > now]
        if self._fetch_btts:
            merged: list[RawEvent] = []
            for ev in events:
                try:   # BTTS comes from the per-event endpoint; failure only drops BTTS for that event
                    extra = await self._get(f"/sports/{league_provider_key}/events/{ev.provider_event_id}/odds",
                                            {"regions": self._regions, "markets": "btts", "oddsFormat": "decimal",
                                             "dateFormat": "iso"}, expect=dict)
                    pe = parse_event(extra)
                    if pe:
                        by_key = {b.key: b for b in ev.bookmakers}
                        for b in pe.bookmakers:
                            if b.key in by_key:
                                old = by_key[b.key]
                                by_key[b.key] = RawBookmaker(old.key, old.title, old.last_update, old.markets + b.markets)
                            else:
                                by_key[b.key] = b
                        ev = RawEvent(ev.provider_event_id, ev.league_provider_key, ev.home, ev.away,
                                      ev.commence_utc, list(by_key.values()))
                except ProviderRateLimited:
                    raise
                except ProviderError:
                    log.warning("btts fetch failed for one event")
                merged.append(ev)
            events = merged
        # attach the league key we asked for (the payload field is advisory only)
        return [RawEvent(e.provider_event_id, league_provider_key, e.home, e.away, e.commence_utc, e.bookmakers)
                for e in events]

    async def fetch_results(self, league_provider_key: str, now: datetime) -> list[RawResult]:
        data = await self._get(f"/sports/{league_provider_key}/scores", {"daysFrom": 3, "dateFormat": "iso"})
        out: list[RawResult] = []
        for e in data:
            if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                continue
            if not e.get("completed"):
                continue
            scores = {s.get("name"): s.get("score") for s in (e.get("scores") or []) if isinstance(s, dict)}
            try:
                hg, ag = int(scores[e["home_team"]]), int(scores[e["away_team"]])
            except (KeyError, TypeError, ValueError):
                continue   # unparseable => treated as unresolved, never guessed
            out.append(RawResult(e["id"], e["home_team"], e["away_team"], _dt(e.get("commence_time")),
                                 "finished", hg, ag, {"last_update": str(e.get("last_update"))}))
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
