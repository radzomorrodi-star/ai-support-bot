"""USDT on BNB Smart Chain (BEP20) - DEMO/MOCK payment layer.

NOTHING here talks to a blockchain, holds keys, or moves funds. `MockChain` simulates an RPC node so the
deposit pipeline (validation, confirmations, replay protection, reconciliation) can be exercised.

!! CONTRACT ADDRESS - VERIFY BEFORE ANY REAL USE !!
0x55d398326f99059fF775485246999027B3197955 is the widely-listed "USDT (BSC-USD)" BEP20 token on BNB Smart
Chain (chain id 56). Public sources disagree on whether it is a Tether-issued or Binance-bridged token.
It was NOT confirmed against an authoritative primary source (tether.to transparency page / BscScan verified
contract) in this build. A licensed operator's compliance team must verify it independently, and the
decimals (18 on BSC, unlike 6 on Ethereum) before enabling anything. It is config, not trust.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import compliance
from app.config import Settings
from app.db.models import PaymentTransaction
from app.security import security_event
from app.services import wallet
from app.services.audit import append_audit

BSC_CHAIN_ID = 56
USDT_BSC_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"   # UNVERIFIED - see module docstring
USDT_BSC_DECIMALS = 18
MIN_CONFIRMATIONS = 15
_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


class PaymentRejected(Exception):
    pass


class ReplayedTransaction(PaymentRejected):
    pass


@dataclass(frozen=True)
class ChainTransfer:
    chain_id: int
    tx_hash: str
    log_index: int
    token_contract: str
    to_address: str
    amount_base_units: int          # raw token units (18 decimals on BSC)
    confirmations: int


class MockChain:
    """Stand-in for an RPC node: the *only* source of truth the provider trusts (never caller-supplied data)."""

    def __init__(self):
        self._tx: dict[tuple[str, int], ChainTransfer] = {}

    def mine(self, t: ChainTransfer) -> None:
        self._tx[(t.tx_hash.lower(), t.log_index)] = t

    def get(self, tx_hash: str, log_index: int = 0) -> ChainTransfer | None:
        return self._tx.get((tx_hash.lower(), log_index))

    def set_confirmations(self, tx_hash: str, n: int, log_index: int = 0) -> None:
        t = self._tx[(tx_hash.lower(), log_index)]
        self._tx[(tx_hash.lower(), log_index)] = ChainTransfer(**{**t.__dict__, "confirmations": n})


def mock_deposit_address(customer_id: int) -> str:
    """Deterministic MOCK address. Real deployments must use provider-issued addresses (no keys held here)."""
    return "0x" + format(customer_id, "x").rjust(40, "0")[-40:]


def base_units_to_minor(base_units: int) -> int:
    """18-decimal token units -> 2-decimal demo minor units (floor), exact integer math."""
    return base_units // 10 ** (USDT_BSC_DECIMALS - 2)


class MockPaymentProvider:
    def __init__(self, chain: MockChain, settings: Settings):
        self.chain, self.settings = chain, settings

    async def ingest_deposit(self, s: AsyncSession, customer_id: int, tx_hash: str, log_index: int = 0
                             ) -> PaymentTransaction:
        """Validate a claimed deposit against the (mock) chain; credit the DEMO wallet exactly once."""
        if not _TX.match(tx_hash or ""):
            await security_event(s, "deposit_bad_tx_format", "warn", actor=str(customer_id))
            raise PaymentRejected("invalid transaction id")
        t = self.chain.get(tx_hash, log_index)
        if t is None:
            await security_event(s, "deposit_unknown_tx", "warn", actor=str(customer_id), tx=tx_hash.lower())
            raise PaymentRejected("transaction not found on chain")
        if t.chain_id != BSC_CHAIN_ID:
            raise PaymentRejected("wrong chain")
        if t.token_contract.lower() != USDT_BSC_CONTRACT.lower():
            await security_event(s, "deposit_wrong_token", "high", actor=str(customer_id), tx=tx_hash.lower())
            raise PaymentRejected("wrong token contract")
        if not _ADDR.match(t.to_address) or t.to_address.lower() != mock_deposit_address(customer_id):
            await security_event(s, "deposit_wrong_recipient", "high", actor=str(customer_id), tx=tx_hash.lower())
            raise PaymentRejected("transaction is not addressed to this customer's deposit address")
        minor = base_units_to_minor(t.amount_base_units)
        if minor <= 0:
            raise PaymentRejected("amount too small")

        existing = (await s.execute(select(PaymentTransaction).where(
            PaymentTransaction.chain_id == t.chain_id, PaymentTransaction.tx_hash == t.tx_hash.lower(),
            PaymentTransaction.log_index == log_index))).scalar()
        if existing is None:
            row = PaymentTransaction(chain_id=t.chain_id, tx_hash=t.tx_hash.lower(), log_index=log_index,
                                     token_contract=t.token_contract.lower(), to_address=t.to_address.lower(),
                                     amount_minor=minor, confirmations=t.confirmations, customer_id=customer_id,
                                     status="pending", is_mock=True)
            try:
                async with s.begin_nested():
                    s.add(row)
                    await s.flush()
            except IntegrityError:
                existing = row = (await s.execute(select(PaymentTransaction).where(
                    PaymentTransaction.tx_hash == t.tx_hash.lower()))).scalar()
            else:
                existing = None
        else:
            row = existing
        if row.customer_id != customer_id:     # someone else's tx id replayed by another customer
            await security_event(s, "deposit_replay_other_customer", "high", actor=str(customer_id), tx=row.tx_hash)
            raise ReplayedTransaction("transaction belongs to another account")
        row.confirmations = t.confirmations
        if row.status == "credited":
            await security_event(s, "deposit_replay", "warn", actor=str(customer_id), tx=row.tx_hash)
            raise ReplayedTransaction("transaction already credited")
        if t.confirmations >= MIN_CONFIRMATIONS:
            await wallet.apply(s, customer_id, row.amount_minor, "demo_grant",
                               f"dep:{row.chain_id}:{row.tx_hash}:{row.log_index}", "payment", row.tx_hash)
            row.status = "credited"
            await append_audit(s, self.settings, "system", "deposit.credited_mock", "payment", row.tx_hash,
                               {"amount_minor": row.amount_minor, "customer_id": customer_id, "mock": True})
        return row


def get_payment_provider(settings: Settings, cfg: dict | None, chain: MockChain) -> MockPaymentProvider:
    """Factory. If the compliance gate were ever open there is STILL no real provider in this build."""
    ok, _ = compliance.gate_status(settings, cfg)
    if ok:  # unreachable while REAL_MONEY_CODE_PATH_IMPLEMENTED is False; fail loudly if someone flips it
        raise NotImplementedError("No audited custody/payment provider integrated; real payments unsupported")
    return MockPaymentProvider(chain, settings)


@dataclass
class WithdrawalApprovalPolicy:
    """Design placeholder for the future: separation of duties (requester != approvers, N distinct approvers)."""
    required_approvals: int = 2

    def can_release(self, requester_admin: int, approvers: set[int]) -> bool:
        return len(approvers - {requester_admin}) >= self.required_approvals


async def request_withdrawal(s: AsyncSession, settings: Settings, cfg: dict | None, customer_id: int,
                             amount_minor: int, to_address: str) -> None:
    """ALWAYS blocked in this build. The attempt is recorded as a security event."""
    try:
        compliance.require_real_money(settings, cfg)
    except compliance.FeatureDisabled:
        await security_event(s, "withdrawal_attempt_blocked", "high", actor=str(customer_id), amount=amount_minor)
        raise
    raise NotImplementedError("withdrawals are not implemented (no hot-wallet by design)")
