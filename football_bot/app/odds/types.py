"""Provider-neutral raw types. Everything coming from an API is UNTRUSTED until normalised."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class RawOutcome:
    name: str
    price: Decimal | None
    point: Decimal | None = None


@dataclass(frozen=True)
class RawMarket:
    key: str                       # provider market key: h2h | totals | btts
    outcomes: list[RawOutcome]
    last_update: datetime | None = None
    suspended: bool = False


@dataclass(frozen=True)
class RawBookmaker:
    key: str
    title: str
    last_update: datetime | None
    markets: list[RawMarket]


@dataclass(frozen=True)
class RawEvent:
    provider_event_id: str
    league_provider_key: str
    home: str
    away: str
    commence_utc: datetime
    bookmakers: list[RawBookmaker] = field(default_factory=list)


@dataclass(frozen=True)
class RawResult:
    provider_event_id: str
    home: str
    away: str
    commence_utc: datetime | None
    final_status: str              # finished | postponed | cancelled | abandoned | in_progress
    home_goals: int | None
    away_goals: int | None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NormQuote:
    bookmaker: str                 # canonical (bet365, pinnacle, ...)
    market: str                    # 1x2 | ou25 | btts
    selection: str                 # home|draw|away | over|under | yes|no
    odds_milli: int
    last_update: datetime
    provider_bookmaker_key: str


@dataclass(frozen=True)
class Rejected:
    bookmaker: str
    market: str
    selection: str
    reason: str


class ProviderError(RuntimeError):
    pass


class ProviderRateLimited(ProviderError):
    pass
