"""Admin API. Every route: IP allowlist -> bearer session -> RBAC permission -> audit (writes & PII reads)."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import admin_auth, compliance
from app.admin_auth import AuthError
from app.db.base import utcnow
from app.db.models import (AdminSession, ApiUsage, AuditEvent, Bet, Claim, Competition, Complaint, Customer, Event,
                           EventOutcome, LedgerEntry, SecurityEvent, SuspendedMarket)
from app.db.session import transaction
from app.odds.service import market_view
from app.ratelimit import allow
from app.security import security_event, sha256_hex
from app.services import claims, opconfig, settlement, wallet
from app.services.audit import append_audit, verify_chain

router = APIRouter()


def rt_of(request: Request):
    return request.app.state.rt


def ip_of(request: Request) -> str | None:
    return request.client.host if request.client else None   # X-Forwarded-For is deliberately NOT trusted


def need(perm: str) -> Callable:
    async def dep(request: Request) -> admin_auth.AdminUser:
        rt = rt_of(request)
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None
        async with rt.sm() as s:
            try:
                return await admin_auth.require(s, rt.settings, token, ip_of(request), perm)
            except AuthError as e:
                await s.commit()
                raise HTTPException(403 if str(e) == "forbidden" else 401, str(e))
    return dep


class LoginIn(BaseModel):
    telegram_id: int = Field(gt=0)
    password: str = Field(min_length=1, max_length=200)
    totp: str = Field(pattern=r"^\d{6}$")


@router.post("/login")
async def login(body: LoginIn, request: Request):
    rt = rt_of(request)
    ip = ip_of(request)
    if not await allow(rt.kv, f"adminlogin:{ip}", 10, 60):
        raise HTTPException(429, "too many attempts")
    async with rt.sm() as s:
        try:
            tok = await admin_auth.login(s, rt.settings, body.telegram_id, body.password, body.totp, ip)
            await s.commit()
            return {"token": tok, "expires_in": rt.settings.admin_session_ttl_seconds}
        except AuthError:
            await s.commit()
            raise HTTPException(401, "invalid credentials")


@router.post("/logout")
async def logout(request: Request, a=Depends(need("customers:read"))):
    rt = rt_of(request)
    token = request.headers["authorization"].removeprefix("Bearer ").strip()
    async with transaction(rt.sm) as s:
        sess = await s.get(AdminSession, sha256_hex(token))
        if sess:
            sess.revoked = True
    return Response(status_code=204)


def actor(a) -> str:
    return f"admin:{a.telegram_id}"


@router.get("/customers/{tid}")
async def customer(tid: int, request: Request, a=Depends(need("customers:read"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        c = await s.get(Customer, tid)
        if not c:
            raise HTTPException(404)
        await append_audit(s, rt.settings, actor(a), "admin.read_customer", "customer", tid, {})
        return {"customer_number": c.telegram_id, "username": c.username, "status": c.status, "timezone": c.timezone,
                "self_excluded_until": c.self_excluded_until, "daily_limit_minor": c.daily_stake_limit_minor,
                "balance_minor": await wallet.balance(s, tid), "demo": True, "created_at": c.created_at}


@router.get("/customers/{tid}/bets")
async def customer_bets(tid: int, request: Request, a=Depends(need("bets:read"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        await append_audit(s, rt.settings, actor(a), "admin.read_bets", "customer", tid, {})
        rows = (await s.execute(select(Bet).where(Bet.customer_id == tid).order_by(Bet.created_at.desc()).limit(200))).scalars()
        return [{"bet_id": b.id, "event_id": b.event_id, "market": b.market, "selection": b.selection,
                 "odds_milli": b.odds_milli, "stake_minor": b.stake_minor, "payout_minor": b.payout_minor,
                 "status": b.status, "created_at": b.created_at} for b in rows]


@router.get("/wallets/{tid}")
async def wallet_view(tid: int, request: Request, a=Depends(need("wallets:read"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        await append_audit(s, rt.settings, actor(a), "admin.read_wallet", "customer", tid, {})
        rows = (await s.execute(select(LedgerEntry).where(LedgerEntry.customer_id == tid)
                                .order_by(LedgerEntry.id.desc()).limit(100))).scalars()
        return {"balance_minor": await wallet.balance(s, tid), "demo": True,
                "ledger": [{"id": r.id, "kind": r.kind, "amount_minor": r.amount_minor,
                            "balance_after_minor": r.balance_after_minor, "ref": r.ref_id, "at": r.created_at} for r in rows]}


@router.get("/fixtures")
async def fixtures(request: Request, a=Depends(need("fixtures:read"))):
    rt = rt_of(request)
    now = utcnow()
    async with rt.sm() as s:
        evs = (await s.execute(select(Event).order_by(Event.kickoff_utc.desc()).limit(100))).scalars().all()
        out = []
        for e in evs:
            o = (await s.execute(select(EventOutcome).where(EventOutcome.event_id == e.id)
                                 .order_by(EventOutcome.id.desc()).limit(1))).scalar()
            openb = (await s.execute(select(func.count()).select_from(Bet).where(Bet.event_id == e.id, Bet.status == "open"))).scalar()
            out.append({"id": e.id, "competition": e.competition_key, "home": e.home, "away": e.away,
                        "kickoff_utc": e.kickoff_utc, "status": e.status, "open_bets": openb,
                        "priced_markets": [m for m in ("1x2", "ou25", "btts") if await market_view(s, e.id, m, now)],
                        "outcome": None if not o else {"status": o.final_status, "score": [o.home_goals, o.away_goals],
                                                       "by": o.decided_by}})
        return out


@router.get("/odds/health")
async def odds_health(request: Request, a=Depends(need("odds:read"))):
    rt = rt_of(request)
    async with rt.sm() as s:
        rows = (await s.execute(select(ApiUsage).order_by(ApiUsage.id.desc()).limit(200))).scalars().all()
        prov: dict[str, dict] = {}
        for r in rows:
            p = prov.setdefault(r.provider, {"calls": 0, "errors": 0, "last_ok": None, "last_error": None,
                                             "quota_remaining": None, "quota_used": None, "avg_latency_ms": 0})
            p["calls"] += 1
            p["errors"] += 0 if r.ok else 1
            if r.ok and p["last_ok"] is None:
                p["last_ok"] = r.ts
            if not r.ok and p["last_error"] is None:
                p["last_error"] = {"at": r.ts, "http": r.http_status, "error": r.error}
            if p["quota_remaining"] is None and r.quota_remaining is not None:
                p["quota_remaining"], p["quota_used"] = r.quota_remaining, r.quota_used
            p["avg_latency_ms"] += (r.latency_ms or 0)
        for p in prov.values():
            p["avg_latency_ms"] = p["avg_latency_ms"] // max(p["calls"], 1)
        comps = (await s.execute(select(Competition))).scalars().all()
        return {"providers": prov, "configured_primary": rt.settings.odds_primary_provider,
                "competitions": [c.key for c in comps]}


class SuspendIn(BaseModel):
    event_id: int | None = None
    market: str | None = Field(default=None, pattern=r"^(1x2|ou25|btts)$")
    reason: str = Field(min_length=3, max_length=200)


@router.get("/markets/suspended")
async def suspended(request: Request, a=Depends(need("odds:read"))):
    async with rt_of(request).sm() as s:
        rows = (await s.execute(select(SuspendedMarket).where(SuspendedMarket.lifted_at.is_(None)))).scalars()
        return [{"id": r.id, "event_id": r.event_id, "market": r.market, "reason": r.reason, "by": r.created_by} for r in rows]


@router.post("/markets/suspend")
async def suspend(body: SuspendIn, request: Request, a=Depends(need("markets:suspend"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        m = SuspendedMarket(event_id=body.event_id, market=body.market, reason=body.reason, created_by=actor(a))
        s.add(m)
        await s.flush()
        await append_audit(s, rt.settings, actor(a), "market.suspended", "market", m.id, body.model_dump())
        return {"id": m.id}


@router.post("/markets/lift/{mid}")
async def lift(mid: int, request: Request, a=Depends(need("markets:suspend"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        m = await s.get(SuspendedMarket, mid)
        if not m or m.lifted_at:
            raise HTTPException(404)
        m.lifted_at = utcnow()
        await append_audit(s, rt.settings, actor(a), "market.lifted", "market", mid, {})
    return {"ok": True}


class DecideIn(BaseModel):
    event_id: int
    final_status: str = Field(pattern=r"^(finished|postponed|cancelled|abandoned)$")
    home_goals: int | None = Field(default=None, ge=0, le=99)
    away_goals: int | None = Field(default=None, ge=0, le=99)
    reason: str = Field(min_length=5, max_length=300)


@router.post("/settlement/decide")
async def decide(body: DecideIn, request: Request, a=Depends(need("settlement:decide"))):
    rt = rt_of(request)
    try:
        async with transaction(rt.sm) as s:
            o = await settlement.admin_decide_outcome(s, rt.settings, actor(a), body.event_id, body.final_status,
                                                      body.home_goals, body.away_goals, body.reason, utcnow())
            oid = o.id
    except settlement.SettlementError as e:
        raise HTTPException(409, str(e))
    n = await settlement.settle_pending(rt.sm, rt.settings, utcnow())
    return {"outcome_id": oid, "bets_settled": n}


@router.post("/settlement/correct")
async def correct(body: DecideIn, request: Request, a=Depends(need("settlement:correct"))):
    rt = rt_of(request)
    try:
        return await settlement.apply_correction(rt.sm, rt.settings, actor(a), body.event_id, body.final_status,
                                                 body.home_goals, body.away_goals, body.reason, utcnow())
    except settlement.SettlementError as e:
        raise HTTPException(409, str(e))


@router.get("/claims")
async def list_claims(request: Request, status: str | None = None, a=Depends(need("claims:read"))):
    async with rt_of(request).sm() as s:
        q = select(Claim).order_by(Claim.id.desc()).limit(200)
        if status:
            q = q.where(Claim.status == status)
        return [{"id": c.id, "bet_id": c.bet_id, "customer": c.customer_id, "amount_minor": c.amount_minor,
                 "status": c.status, "deadline_at": c.deadline_at, "requested_at": c.requested_at,
                 "late": c.late_request} for c in (await s.execute(q)).scalars()]


class ResolveIn(BaseModel):
    approve: bool
    reason: str = Field(min_length=3, max_length=300)


@router.post("/claims/{cid}/resolve")
async def resolve_claim(cid: int, body: ResolveIn, request: Request, a=Depends(need("claims:resolve"))):
    rt = rt_of(request)
    try:
        async with transaction(rt.sm) as s:
            c = await claims.resolve(s, rt.settings, actor(a), cid, body.approve, body.reason, utcnow())
            return {"status": c.status}
    except claims.ClaimNotFound:
        raise HTTPException(404)
    except claims.ClaimError as e:
        raise HTTPException(409, str(e))


@router.get("/complaints")
async def complaints(request: Request, a=Depends(need("complaints:read"))):
    async with rt_of(request).sm() as s:
        rows = (await s.execute(select(Complaint).order_by(Complaint.id.desc()).limit(100))).scalars()
        return [{"id": c.id, "customer": c.customer_id, "text": c.text, "status": c.status, "at": c.created_at} for c in rows]


@router.get("/security/alerts")
async def alerts(request: Request, a=Depends(need("security:read"))):
    async with rt_of(request).sm() as s:
        rows = (await s.execute(select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(200))).scalars()
        return [{"id": e.id, "ts": e.ts, "kind": e.kind, "severity": e.severity, "actor": e.actor, "data": e.data,
                 "ack": e.acknowledged} for e in rows]


@router.post("/security/alerts/{eid}/ack")
async def ack(eid: int, request: Request, a=Depends(need("security:ack"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        e = await s.get(SecurityEvent, eid)
        if not e:
            raise HTTPException(404)
        e.acknowledged = True
        await append_audit(s, rt.settings, actor(a), "security.ack", "security_event", eid, {})
    return {"ok": True}


@router.get("/audit")
async def audit(request: Request, limit: int = 100, a=Depends(need("audit:read"))):
    async with rt_of(request).sm() as s:
        rows = (await s.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(max(limit, 1), 500)))).scalars()
        return [{"id": r.id, "ts": r.ts, "actor": r.actor, "action": r.action, "entity": r.entity,
                 "entity_id": r.entity_id, "data": r.data, "hash": r.hash} for r in rows]


@router.get("/audit/verify")
async def audit_verify(request: Request, a=Depends(need("audit:read"))):
    rt = rt_of(request)
    async with rt.sm() as s:
        ok, bad = await verify_chain(s, rt.settings)
    return {"chain_ok": ok, "first_bad_id": bad}


@router.get("/audit/export")
async def audit_export(request: Request, a=Depends(need("audit:export"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        await append_audit(s, rt.settings, actor(a), "audit.export", "audit", "all", {})
        body = await compliance.export_audit_jsonl(s, rt.settings)
    return Response(body, media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=audit.jsonl"})


@router.get("/config")
async def get_config(request: Request, a=Depends(need("customers:read"))):
    rt = rt_of(request)
    async with rt.sm() as s:
        v, cfg = await opconfig.load_active(s, rt.settings)
        ok, unmet = compliance.gate_status(rt.settings, cfg)
    return {"version": v, "config": cfg, "real_money_gate_open": ok, "gate_unmet": unmet}


class MarginIn(BaseModel):
    margin_bp: int = Field(ge=0, le=2000)
    reason: str = Field(min_length=5, max_length=300)


@router.post("/config/margin")
async def set_margin(body: MarginIn, request: Request, a=Depends(need("config:write"))):
    rt = rt_of(request)
    async with transaction(rt.sm) as s:
        v, cfg = await opconfig.load_active(s, rt.settings)
        row = await opconfig.publish(s, rt.settings, {**cfg, "margin_bp": body.margin_bp}, actor(a), body.reason)
        return {"version": row.version, "margin_bp": body.margin_bp}
