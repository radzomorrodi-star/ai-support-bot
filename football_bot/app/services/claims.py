"""Ten-day winnings-claim workflow.

SAFEGUARD: the deadline NEVER forfeits winnings. After the deadline a claim moves to `admin_review`
(still requestable by the customer, flagged `late_request`). Only an authorised admin can resolve it.
Real-money claim limitation would need jurisdiction-specific legal approval (see docs/COMPLIANCE_CHECKLIST.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Bet, Claim
from app.db.session import transaction
from app.services import wallet
from app.services.audit import append_audit
from app.services.customers import notify


class ClaimError(Exception):
    pass


class ClaimDuplicate(ClaimError):
    pass


class ClaimNotFound(ClaimError):
    pass


async def create_for_win(s: AsyncSession, settings: Settings, cfg: dict, bet: Bet, now: datetime) -> Claim:
    existing = (await s.execute(select(Claim).where(Claim.bet_id == bet.id))).scalar()
    if existing:
        if existing.resolved_by == "correction" and existing.status == "rejected":   # re-win after a correction
            existing.status, existing.resolved_by, existing.resolved_at = "pending_request", None, None
            existing.deadline_at, existing.reminders_sent = now + timedelta(days=cfg["claim_window_days"]), 0
            await append_audit(s, settings, "system", "claim.reopened", "claim", existing.id, {"bet_id": bet.id})
        return existing
    c = Claim(bet_id=bet.id, customer_id=bet.customer_id, amount_minor=bet.payout_minor, status="pending_request",
              deadline_at=now + timedelta(days=cfg["claim_window_days"]), created_at=now)
    s.add(c)
    await s.flush()
    await append_audit(s, settings, "system", "claim.created", "claim", c.id,
                       {"bet_id": bet.id, "amount_minor": c.amount_minor, "deadline": c.deadline_at.isoformat()})
    await notify(s, bet.customer_id, "win", {"bet_id": bet.id, "amount_minor": c.amount_minor,
                                              "deadline": c.deadline_at.isoformat()}, f"win:{bet.id}")
    return c


async def request_claim(sm: async_sessionmaker[AsyncSession], settings: Settings, customer_id: int, bet_id: str,
                        now: datetime) -> Claim:
    async with transaction(sm) as s:
        c = (await s.execute(select(Claim).where(Claim.bet_id == bet_id, Claim.customer_id == customer_id))).scalar()
        if c is None:
            raise ClaimNotFound()
        # atomic state transition: only one request can ever win
        r = await s.execute(update(Claim).where(
            Claim.id == c.id, Claim.status.in_(("pending_request", "admin_review")))
            .values(status="requested", requested_at=now, late_request=now > c.deadline_at))
        if r.rowcount != 1:
            raise ClaimDuplicate()
        await s.refresh(c)
        await append_audit(s, settings, f"customer:{customer_id}", "claim.requested", "claim", c.id,
                           {"bet_id": bet_id, "late": c.late_request})
        return c


async def sweep(sm: async_sessionmaker[AsyncSession], settings: Settings, cfg: dict, now: datetime) -> dict[str, int]:
    """Reminders before the deadline; flag overdue claims for admin review (never forfeit)."""
    reminded = flagged = 0
    days = sorted(cfg["claim_reminder_days_before"], reverse=True)
    async with transaction(sm) as s:
        pend = (await s.execute(select(Claim).where(Claim.status == "pending_request"))).scalars().all()
        for c in pend:
            if now >= c.deadline_at:
                c.status = "admin_review"
                flagged += 1
                await append_audit(s, settings, "system", "claim.deadline_passed", "claim", c.id,
                                   {"outcome": "admin_review_not_forfeited"})
                await notify(s, c.customer_id, "claim_review", {"bet_id": c.bet_id, "amount_minor": c.amount_minor},
                             f"claimreview:{c.id}")
                continue
            if c.reminders_sent < len(days) and (c.deadline_at - now) <= timedelta(days=days[c.reminders_sent]):
                c.reminders_sent += 1
                reminded += 1
                await notify(s, c.customer_id, "claim_reminder",
                             {"bet_id": c.bet_id, "amount_minor": c.amount_minor, "deadline": c.deadline_at.isoformat()},
                             f"claimrem:{c.id}:{c.reminders_sent}")
    return {"reminded": reminded, "flagged": flagged}


async def resolve(s: AsyncSession, settings: Settings, admin_actor: str, claim_id: int, approve: bool,
                  reason: str, now: datetime) -> Claim:
    """Admin decision. Approval credits the DEMO wallet exactly once (idempotent ledger key)."""
    c = await s.get(Claim, claim_id)
    if c is None:
        raise ClaimNotFound()
    if c.status not in ("requested", "admin_review", "pending_request"):
        raise ClaimError(f"claim already {c.status}")
    if not reason.strip():
        raise ClaimError("reason required")
    if approve:
        await wallet.apply(s, c.customer_id, c.amount_minor, "claim_credit", f"claim:{c.id}", "claim", str(c.id))
        c.status = "approved"
    else:
        c.status = "rejected"
    c.resolved_by, c.resolved_at = admin_actor, now
    await append_audit(s, settings, admin_actor, "claim.approved" if approve else "claim.rejected", "claim", c.id,
                       {"reason": reason[:300], "amount_minor": c.amount_minor})
    await notify(s, c.customer_id, "claim_result", {"approved": approve, "amount_minor": c.amount_minor,
                                                    "bet_id": c.bet_id}, f"claimres:{c.id}")
    return c
