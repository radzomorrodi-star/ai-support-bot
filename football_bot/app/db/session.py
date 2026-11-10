from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base


def make_engine(url: str) -> AsyncEngine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True)
    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _fk(dbapi_conn, _):  # enforce FKs & sane locking in dev/test
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(sm: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One atomic unit of work: commit on success, roll back on any exception."""
    async with sm() as s:
        try:
            yield s
            await s.commit()
        except BaseException:
            await s.rollback()
            raise


async def create_all(engine: AsyncEngine) -> None:  # dev/test only; prod uses Alembic
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
