"""Atomic demo-wallet operations. The balance can never go negative: the guard lives in the UPDATE itself
(plus a DB CHECK constraint), so concurrent debits cannot overdraw regardless of read-then-write races."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, Wallet


class InsufficientFunds(Exception):
    pass


async def balance(s: AsyncSession, customer_id: int) -> int:
    return (await s.execute(select(Wallet.balance_minor).where(Wallet.customer_id == customer_id))).scalar() or 0


async def apply(s: AsyncSession, customer_id: int, delta_minor: int, kind: str, key: str,
                ref_type: str | None = None, ref_id: str | None = None, allow_partial: bool = False) -> int:
    """Apply a signed delta exactly once per idempotency `key`. Returns the amount actually applied.

    * duplicate key  -> no-op, returns the originally applied amount
    * would go < 0   -> InsufficientFunds (or, with allow_partial, clamps a debit to the available balance)
    """
    if delta_minor == 0:
        raise ValueError("zero delta")
    prior = (await s.execute(select(LedgerEntry.amount_minor).where(LedgerEntry.idempotency_key == key))).scalar()
    if prior is not None:
        return prior
    if allow_partial and delta_minor < 0:
        delta_minor = -min(-delta_minor, await balance(s, customer_id))
        if delta_minor == 0:
            return 0
    res = await s.execute(update(Wallet).where(Wallet.customer_id == customer_id,
                                               Wallet.balance_minor + delta_minor >= 0)
                          .values(balance_minor=Wallet.balance_minor + delta_minor))
    if res.rowcount != 1:
        raise InsufficientFunds()
    new_bal = await balance(s, customer_id)
    s.add(LedgerEntry(customer_id=customer_id, kind=kind, amount_minor=delta_minor, balance_after_minor=new_bal,
                      ref_type=ref_type, ref_id=ref_id, idempotency_key=key))
    await s.flush()
    return delta_minor
