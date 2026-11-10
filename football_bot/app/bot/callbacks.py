"""Strict callback-data codec.

Callback data is attacker-controlled (any client can send arbitrary strings). It therefore carries ONLY
opaque identifiers (a server-side row id), never prices, stakes, balances or outcomes. Each verb has an
argument regex; anything else is rejected before any handler logic runs. The acting customer is always
taken from Telegram's authenticated `from_user`, never from the payload.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ID = r"\d{1,12}"
_TOKEN = r"[A-Z0-9]{8,20}"
_VERBS: dict[str, str | None] = {
    "h": None, "lg": None, "ml": None, "mb": None, "rs": None, "wl": None, "tm": None, "sp": None,
    "cm": None, "ex": None, "lm": None,
    "cp": r"[a-z0-9]{2,12}",          # competition key
    "ev": _ID, "sl": _ID, "dt": rf"{_ID}:(1x2|ou25|btts)", "mk": rf"{_ID}:(1x2|ou25|btts)",
    "cf": _TOKEN, "cx": _TOKEN, "bt": _TOKEN, "cl": _TOKEN,
    "exd": r"(1|7|30|180)", "dl": r"(50|100|500)",
}
_COMPILED = {v: (re.compile(rf"^{p}$") if p else None) for v, p in _VERBS.items()}


@dataclass(frozen=True)
class Cb:
    verb: str
    arg: str | None = None

    def pack(self) -> str:
        s = self.verb if self.arg is None else f"{self.verb}:{self.arg}"
        if len(s.encode()) > 64:
            raise ValueError("callback too long")
        return s


def parse(data: str | None) -> Cb | None:
    if not data or len(data) > 64 or not data.isascii():
        return None
    verb, _, arg = data.partition(":")
    rx = _COMPILED.get(verb)
    if verb not in _COMPILED:
        return None
    if rx is None:
        return Cb(verb) if not arg and ":" not in data else None
    return Cb(verb, arg) if rx.match(arg) else None
