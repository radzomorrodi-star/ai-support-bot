"""Compliance module: server-side feature gates + integration points + responsible-gambling controls.

THIS BUILD IS DEMO-ONLY. `REAL_MONEY_CODE_PATH_IMPLEMENTED` is a source-code constant: no environment
variable, database row or admin action can turn real-money features on. Enabling them requires
(1) a code change that implements and reviews the real-money paths, (2) legal approval,
(3) an independent security assessment, (4) the signed config refs below, and (5) the env flag.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.base import utcnow
from app.db.models import AuditEvent, Bet, Customer
from app.security import security_event
from app.services.audit import verify_chain

REAL_MONEY_CODE_PATH_IMPLEMENTED = False   # <- deliberately a constant, see module docstring


class FeatureDisabled(RuntimeError):
    """Raised whenever a real-money capability is invoked while the compliance gate is closed."""


def gate_status(settings: Settings, cfg: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """(allowed, unmet_requirements). `cfg` must be the signature-verified active config or None."""
    unmet: list[str] = []
    if not REAL_MONEY_CODE_PATH_IMPLEMENTED:
        unmet.append("real-money code path not implemented in this build")
    if not settings.real_money_enabled:
        unmet.append("REAL_MONEY_ENABLED is false")
    comp = (cfg or {}).get("compliance") or {}
    for k in ("license_ref", "legal_approval_ref", "security_assessment_ref"):
        if not str(comp.get(k, "")).strip():
            unmet.append(f"signed config compliance.{k} missing")
    if not comp.get("approved_jurisdictions"):
        unmet.append("no approved jurisdictions")
    return (not unmet), unmet


def require_real_money(settings: Settings, cfg: dict[str, Any] | None) -> None:
    ok, unmet = gate_status(settings, cfg)
    if not ok:
        raise FeatureDisabled("; ".join(unmet))


# ---- integration points (all default to "not configured": demo needs none) -----------------------
class AgeVerifier(Protocol):
    async def is_adult(self, customer_id: int) -> bool: ...


class KycProvider(Protocol):
    async def status(self, customer_id: int) -> str: ...


class SanctionsScreener(Protocol):
    async def is_clear(self, customer_id: int, country: str | None) -> bool: ...


class DemoAgeVerifier:
    async def is_adult(self, customer_id: int) -> bool:
        return True  # demo only; a real operator MUST replace this with a verified provider


class DemoKyc:
    async def status(self, customer_id: int) -> str:
        return "not_required_demo"


class DemoSanctions:
    async def is_clear(self, customer_id: int, country: str | None) -> bool:
        return True


def jurisdiction_allowed(country: str | None, cfg: dict[str, Any]) -> bool:
    if country is None:
        return True  # demo: unknown allowed; real mode must require a verified country
    return country.upper() not in {c.upper() for c in cfg.get("blocked_countries", [])}


# ---- responsible gambling ------------------------------------------------------------------------
SELF_EXCLUSION_CHOICES_DAYS = (1, 7, 30, 180)


async def self_exclude(session: AsyncSession, customer_id: int, days: int) -> Any:
    if days not in SELF_EXCLUSION_CHOICES_DAYS:
        raise ValueError("invalid exclusion period")
    c = await session.get(Customer, customer_id)
    until = utcnow() + timedelta(days=days)
    # exclusions can only be extended, never shortened by the customer
    if c.self_excluded_until is None or until > c.self_excluded_until:
        c.self_excluded_until = until
    return c.self_excluded_until


def is_excluded(c: Customer) -> bool:
    return c.self_excluded_until is not None and c.self_excluded_until > utcnow()


async def stake_today_minor(session: AsyncSession, customer_id: int) -> int:
    since = utcnow() - timedelta(hours=24)
    return (await session.execute(select(func.coalesce(func.sum(Bet.stake_minor), 0))
                                  .where(Bet.customer_id == customer_id, Bet.created_at >= since))).scalar() or 0


async def daily_limit_ok(session: AsyncSession, c: Customer, cfg: dict[str, Any], new_stake: int) -> bool:
    limit = c.daily_stake_limit_minor or cfg["default_daily_limit_minor"]
    limit = min(limit, cfg["default_daily_limit_minor"]) if c.daily_stake_limit_minor is None else limit
    return (await stake_today_minor(session, c.telegram_id)) + new_stake <= limit


# ---- transaction monitoring ----------------------------------------------------------------------
async def monitor_bet_velocity(session: AsyncSession, customer_id: int, max_per_10min: int = 20) -> None:
    since = utcnow() - timedelta(minutes=10)
    n = (await session.execute(select(func.count()).select_from(Bet)
                               .where(Bet.customer_id == customer_id, Bet.created_at >= since))).scalar() or 0
    if n >= max_per_10min:
        await security_event(session, "bet_velocity_high", "warn", actor=str(customer_id), count=n)


# ---- privacy / retention -------------------------------------------------------------------------
async def anonymize_customer(session: AsyncSession, customer_id: int) -> None:
    """Erase personal fields on request. Financial/audit records are retained (legal obligation)."""
    c = await session.get(Customer, customer_id)
    if c:
        c.username = None
        c.country_code = None
        c.status = "blocked"


# ---- audit export --------------------------------------------------------------------------------
async def export_audit_jsonl(session: AsyncSession, settings: Settings, since=None) -> str:
    ok, bad = await verify_chain(session, settings)
    q = select(AuditEvent).order_by(AuditEvent.id)
    if since is not None:
        q = q.where(AuditEvent.ts >= since)
    lines = [json.dumps({"chain_ok": ok, "first_bad_id": bad, "exported_at": utcnow().isoformat()})]
    for r in (await session.execute(q)).scalars():
        lines.append(json.dumps({"id": r.id, "ts": r.ts.isoformat(), "actor": r.actor, "action": r.action,
                                 "entity": r.entity, "entity_id": r.entity_id, "data": r.data,
                                 "prev_hash": r.prev_hash, "hash": r.hash}, ensure_ascii=False))
    return "\n".join(lines)
