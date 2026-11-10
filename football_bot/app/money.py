"""Exact money & odds arithmetic. NO floats anywhere.

* Money is an int in minor units: 1 demo-USDT = 100 minor (2 decimals).
* Decimal odds are an int in thousandths ("milli-odds"): 1.85 -> 1850.
* Payouts round DOWN (house-favourable, documented in the terms).
"""
from __future__ import annotations

import re
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation

MINOR_PER_UNIT = 100
ODDS_SCALE = 1000
MIN_ODDS_MILLI = 1010   # sanity floor for any accepted price
MAX_ODDS_MILLI = 1_000_000

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬،", "01234567890123456789.,,")
_STAKE_RE = re.compile(r"^\d{1,7}([.,]\d{1,2})?$")


class MoneyError(ValueError):
    pass


def normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP).strip()


def parse_stake(text: str) -> int:
    """Parse untrusted user text into minor units. Strict: digits, optional 1-2 decimals."""
    t = normalize_digits(text)
    if not _STAKE_RE.match(t):
        raise MoneyError("invalid stake format")
    try:
        d = Decimal(t.replace(",", "."))
    except InvalidOperation as e:  # pragma: no cover
        raise MoneyError("invalid stake") from e
    minor = int((d * MINOR_PER_UNIT).to_integral_value(rounding=ROUND_DOWN))
    if minor <= 0:
        raise MoneyError("stake must be positive")
    return minor


def decimal_to_odds_milli(value: Decimal | str | int) -> int:
    try:
        d = Decimal(str(value))
    except InvalidOperation as e:
        raise MoneyError("invalid odds") from e
    if not d.is_finite():
        raise MoneyError("non-finite odds")
    return int((d * ODDS_SCALE).to_integral_value(rounding=ROUND_HALF_EVEN))


def odds_milli_to_decimal(m: int) -> Decimal:
    return Decimal(m) / ODDS_SCALE


def payout_minor(stake_minor: int, odds_milli: int) -> int:
    if stake_minor <= 0 or odds_milli < MIN_ODDS_MILLI:
        raise MoneyError("bad stake/odds")
    return stake_minor * odds_milli // ODDS_SCALE


def profit_minor(stake_minor: int, odds_milli: int) -> int:
    return payout_minor(stake_minor, odds_milli) - stake_minor
