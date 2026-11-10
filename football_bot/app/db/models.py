"""Schema. Money = integer minor units, odds = integer milli-odds, times = UTC.

Append-only tables (ledger, audit, receipts, settlements, event_results, security_events) are
protected by app code AND by DB triggers (see the Alembic migration, PostgreSQL).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import PK, Base, UTCDateTime, utcnow


class Customer(Base):
    __tablename__ = "customers"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # = customer number
    username: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tehran")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|blocked
    country_code: Mapped[str | None] = mapped_column(String(2))
    age_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    kyc_status: Mapped[str] = mapped_column(String(24), default="not_required_demo")
    terms_version: Mapped[str | None] = mapped_column(String(16))
    self_excluded_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    daily_stake_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Wallet(Base):
    __tablename__ = "wallets"
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), primary_key=True)
    balance_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("balance_minor >= 0", name="ck_wallet_nonneg"),)


class LedgerEntry(Base):
    """Append-only double-entry-style journal; wallet.balance == sum(amount) per customer."""
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # demo_grant|stake|payout|refund|claim_credit|correction
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # signed
    balance_after_minor: Mapped[int] = mapped_column(BigInteger)
    ref_type: Mapped[str | None] = mapped_column(String(24))
    ref_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(96), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Competition(Base):
    __tablename__ = "competitions"
    key: Mapped[str] = mapped_column(String(16), primary_key=True)  # epl, laliga, ...
    provider_key: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    competition_key: Mapped[str] = mapped_column(ForeignKey("competitions.key"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(96))
    home: Mapped[str] = mapped_column(String(96))
    away: Mapped[str] = mapped_column(String(96))
    kickoff_utc: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_event_provider"),)


class SuspendedMarket(Base):
    __tablename__ = "suspended_markets"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))  # None = all events
    market: Mapped[str | None] = mapped_column(String(16))              # None = all markets
    reason: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    lifted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PriceQuote(Base):
    """Immutable pricing calculation snapshot for one outcome. Customers bet on a quote id."""
    __tablename__ = "price_quotes"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    market: Mapped[str] = mapped_column(String(16))
    selection: Mapped[str] = mapped_column(String(16))
    odds_milli: Mapped[int] = mapped_column(Integer)           # customer price
    best_milli: Mapped[int] = mapped_column(Integer)
    median_milli: Mapped[int] = mapped_column(Integer)
    n_quotes: Mapped[int] = mapped_column(Integer)
    margin_bp: Mapped[int] = mapped_column(Integer)
    config_version: Mapped[int] = mapped_column(Integer)
    calc: Mapped[dict] = mapped_column(JSON)                    # full inputs, timestamps, overround checks
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (Index("ix_quote_lookup", "event_id", "market", "selection", "id"),)


class BetDraft(Base):
    """Server-side pending bet. Callback data carries only this id -> client can't tamper values."""
    __tablename__ = "bet_drafts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), index=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("price_quotes.id"))
    stake_minor: Mapped[int | None] = mapped_column(BigInteger)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Bet(Base):
    """Immutable commercial terms. `status`/`settled_at` are the only fields ever updated (by settlement)."""
    __tablename__ = "bets"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("price_quotes.id"))
    market: Mapped[str] = mapped_column(String(16))
    selection: Mapped[str] = mapped_column(String(16))
    odds_milli: Mapped[int] = mapped_column(Integer)
    stake_minor: Mapped[int] = mapped_column(BigInteger)
    payout_minor: Mapped[int] = mapped_column(BigInteger)
    kickoff_utc: Mapped[datetime] = mapped_column(UTCDateTime)
    terms_version: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(8), default="open", index=True)  # open|won|lost|void
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("stake_minor > 0", name="ck_bet_stake"),)


class Receipt(Base):
    __tablename__ = "receipts"
    bet_id: Mapped[str] = mapped_column(ForeignKey("bets.id"), primary_key=True)
    body: Mapped[dict] = mapped_column(JSON)
    body_canonical: Mapped[str] = mapped_column(Text)   # exact bytes that were MAC'd
    integrity_hash: Mapped[str] = mapped_column(String(64))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)  # informational; set once
    pin_status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|pinned|failed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EventResult(Base):
    """Append-only observed results. A correction is a new row superseding an earlier one."""
    __tablename__ = "event_results"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    final_status: Mapped[str] = mapped_column(String(16))  # finished|postponed|cancelled|abandoned
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    raw: Mapped[dict | None] = mapped_column(JSON)


class EventOutcome(Base):
    """The decided outcome of an event (needs two agreeing sources, or an authorised admin decision)."""
    __tablename__ = "event_outcomes"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    final_status: Mapped[str] = mapped_column(String(16))
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    decided_by: Mapped[str] = mapped_column(String(64))       # "system:2-source" | "admin:<id>"
    sources: Mapped[list] = mapped_column(JSON)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("event_outcomes.id"))
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Settlement(Base):
    """Append-only per-bet settlement decision. Corrections reference the superseded row."""
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    bet_id: Mapped[str] = mapped_column(ForeignKey("bets.id"), index=True)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("event_outcomes.id"))
    result: Mapped[str] = mapped_column(String(8))            # won|lost|void
    payout_minor: Mapped[int] = mapped_column(BigInteger)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("settlements.id"))
    decided_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Exactly one *active* (non-superseded) decision per bet is enforced by this unique key on the
    # chain position: first settlement has supersedes_id NULL (unique via partial index in migration),
    # corrections point at the row they replace (each row can be superseded at most once).
    __table_args__ = (UniqueConstraint("supersedes_id", name="uq_settlement_supersedes"),
                      UniqueConstraint("bet_id", "outcome_id", "result", name="uq_settlement_decision"))


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    bet_id: Mapped[str] = mapped_column(ForeignKey("bets.id"), unique=True)   # duplicate prevention
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="pending_request", index=True)
    deadline_at: Mapped[datetime] = mapped_column(UTCDateTime)
    requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    late_request: Mapped[bool] = mapped_column(Boolean, default=False)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SignedConfig(Base):
    """Append-only versioned operator configuration (margin, limits, terms...). HMAC-signed."""
    __tablename__ = "signed_configs"
    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_canonical: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    """Hash-chained, append-only audit log (financial + admin + settlement)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(8))  # info|warn|high|critical
    actor: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminUser(Base):
    __tablename__ = "admin_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(200))
    totp_secret_enc: Mapped[str] = mapped_column(String(300))
    totp_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_totp_step: Mapped[int] = mapped_column(BigInteger, default=0)   # replay protection
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.telegram_id"))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class PaymentTransaction(Base):
    """MOCK blockchain tx records. Replay protection: (chain_id, tx_hash, log_index) unique."""
    __tablename__ = "payment_transactions"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(Integer)
    tx_hash: Mapped[str] = mapped_column(String(66))
    log_index: Mapped[int] = mapped_column(Integer, default=0)
    token_contract: Mapped[str] = mapped_column(String(42))
    to_address: Mapped[str] = mapped_column(String(42))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|confirmed|credited|rejected
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.telegram_id"))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_chain_tx"),)


class WithdrawalRequest(Base):
    """Architecture placeholder: requests need N distinct approvers; nothing is ever sent on-chain."""
    __tablename__ = "withdrawal_requests"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    to_address: Mapped[str] = mapped_column(String(42))
    status: Mapped[str] = mapped_column(String(16), default="blocked_by_gate")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), index=True)
    text: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(12), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    http_status: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    quota_remaining: Mapped[int | None] = mapped_column(Integer)
    quota_used: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(200))


class ProcessedUpdate(Base):
    """Telegram update_id replay protection (durable fallback; Redis is the fast path)."""
    __tablename__ = "processed_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    """Outbox: customer messages are persisted first, then delivered by the worker (retry-safe)."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.telegram_id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(96), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
