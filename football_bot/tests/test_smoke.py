from sqlalchemy import select

from app.db.models import PriceQuote
from tests.conftest import place, register


async def test_world_has_prices_and_bet_flow(world):
    async with world.sm() as s:
        n = (await s.execute(select(PriceQuote))).scalars().all()
        assert len(n) > 50
    await register(world)
    bet, rc, created = await place(world)
    assert created and bet.status == "open" and rc.integrity_hash
