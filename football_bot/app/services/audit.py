"""Hash-chained append-only audit log. Each row's hash = HMAC(prev_hash || canonical(row))."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.base import utcnow
from app.db.models import AuditEvent
from app.security import canonical, hmac_hex

GENESIS = "0" * 64


def _row_material(prev: str, ts_iso: str, actor: str, action: str, entity: str, entity_id: str, data: dict) -> str:
    return canonical({"prev": prev, "ts": ts_iso, "actor": actor, "action": action,
                      "entity": entity, "entity_id": entity_id, "data": data})


async def append_audit(session: AsyncSession, settings: Settings, actor: str, action: str,
                       entity: str, entity_id: str | int, data: dict[str, Any] | None = None) -> AuditEvent:
    data = data or {}
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":   # serialise chain writers
        await session.execute(text("SELECT pg_advisory_xact_lock(727001)"))
    last = (await session.execute(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1))).scalar()
    prev = last or GENESIS
    ts = utcnow()
    h = hmac_hex(settings.audit_hmac_key.get_secret_value(),
                 _row_material(prev, ts.isoformat(), actor, action, entity, str(entity_id), data), "AUDIT_HMAC_KEY")
    ev = AuditEvent(ts=ts, actor=actor, action=action, entity=entity, entity_id=str(entity_id),
                    data=data, prev_hash=prev, hash=h)
    session.add(ev)
    await session.flush()
    return ev


async def verify_chain(session: AsyncSession, settings: Settings) -> tuple[bool, int | None]:
    """Returns (ok, first_bad_id)."""
    prev = GENESIS
    rows = (await session.execute(select(AuditEvent).order_by(AuditEvent.id))).scalars()
    for r in rows:
        want = hmac_hex(settings.audit_hmac_key.get_secret_value(),
                        _row_material(prev, r.ts.isoformat(), r.actor, r.action, r.entity, r.entity_id, r.data),
                        "AUDIT_HMAC_KEY")
        if r.prev_hash != prev or r.hash != want:
            return False, r.id
        prev = r.hash
    return True, None
