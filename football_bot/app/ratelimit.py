"""Fixed-window rate limiting + update replay protection. Redis in prod; in-process fallback for dev/tests."""
from __future__ import annotations

import time
from typing import Protocol


class KV(Protocol):
    async def incr(self, k: str) -> int: ...
    async def expire(self, k: str, s: int) -> bool: ...
    async def set(self, k: str, v: str, nx: bool = False, ex: int | None = None): ...


class MemoryKV:
    def __init__(self):
        self._d: dict[str, tuple[int, float]] = {}

    def _alive(self, k):
        v = self._d.get(k)
        if v and v[1] < time.monotonic():
            del self._d[k]
            return None
        return v

    async def incr(self, k):
        v = self._alive(k)
        n = (v[0] if v else 0) + 1
        self._d[k] = (n, v[1] if v else time.monotonic() + 3600)
        return n

    async def expire(self, k, s):
        v = self._alive(k)
        if v:
            self._d[k] = (v[0], time.monotonic() + s)
        return True

    async def set(self, k, v, nx=False, ex=None):
        if nx and self._alive(k):
            return None
        self._d[k] = (1, time.monotonic() + (ex or 3600))
        return True


async def allow(kv: KV, key: str, limit: int, window_s: int) -> bool:
    k = f"rl:{key}:{int(time.time() // window_s)}"
    n = await kv.incr(k)
    if n == 1:
        await kv.expire(k, window_s + 1)
    return n <= limit


async def first_seen(kv: KV, key: str, ttl_s: int = 86400) -> bool:
    """True only the first time `key` is seen (SET NX). Used for Telegram update_id replay protection."""
    return bool(await kv.set(f"seen:{key}", "1", nx=True, ex=ttl_s))
