from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.odds.types import RawEvent, RawResult


class OddsProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_events(self, league_provider_key: str, now: datetime) -> list[RawEvent]:
        """Upcoming events with bookmaker prices for one competition. Must enforce HTTP timeouts."""

    async def fetch_results(self, league_provider_key: str, now: datetime) -> list[RawResult]:
        """Optional: completed-match scores from this provider (used as ONE settlement source)."""
        return []

    async def aclose(self) -> None:  # pragma: no cover
        return None
