"""Result sources. A result only counts toward settlement when >= 2 DISTINCT sources agree
(or an authorised admin records an explicit, audited decision)."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.odds.providers.base import OddsProvider
from app.odds.types import RawResult


class ResultSource(Protocol):
    name: str

    async def fetch(self, league_provider_key: str, now: datetime) -> list[RawResult]: ...


class ProviderResultSource:
    """Adapter exposing an odds provider's score feed as a result source."""

    def __init__(self, provider: OddsProvider, name: str | None = None):
        self.provider, self.name = provider, name or provider.name

    async def fetch(self, league_provider_key: str, now: datetime) -> list[RawResult]:
        return await self.provider.fetch_results(league_provider_key, now)


class StaticResultSource:
    """In-memory source for the demo and tests. NOT for production use."""

    def __init__(self, name: str, results: list[RawResult] | None = None):
        self.name, self.results = name, results or []

    async def fetch(self, league_provider_key: str, now: datetime) -> list[RawResult]:
        return list(self.results)
