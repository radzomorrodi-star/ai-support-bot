"""Admin authentication & RBAC.

Layers: Telegram-ID allowlist (env) -> optional IP allowlist -> password (scrypt) -> TOTP 2FA (replay-proof,
brute-force lockout) -> short-lived opaque session token (stored hashed) -> role permission check per action.
"""
from __future__ import annotations

import ipaddress
from datetime import timedelta

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.base import utcnow
from app.db.models import AdminSession, AdminUser
from app.security import (decrypt_secret, encrypt_secret, hash_password, new_token, security_event, sha256_hex,
                          verify_password)
from app.services.audit import append_audit

ROLES: dict[str, set[str]] = {
    "viewer":     {"customers:read", "bets:read", "fixtures:read", "odds:read", "settlement:read", "claims:read",
                   "wallets:read"},
    "support":    {"customers:read", "bets:read", "claims:read", "wallets:read", "complaints:read", "claims:resolve"},
    "settlement": {"fixtures:read", "settlement:read", "settlement:decide", "settlement:correct", "odds:read",
                   "markets:suspend", "bets:read"},
    "compliance": {"customers:read", "bets:read", "audit:read", "audit:export", "security:read", "security:ack",
                   "complaints:read", "claims:read", "wallets:read"},
    "superadmin": {"*"},
}
MAX_FAILS = 5
LOCK_MINUTES = 15


class AuthError(Exception):
    pass


def has_perm(role: str, perm: str) -> bool:
    p = ROLES.get(role, set())
    return "*" in p or perm in p


def ip_allowed(settings: Settings, ip: str | None) -> bool:
    if not settings.admin_ip_allowlist:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in ipaddress.ip_network(c, strict=False) for c in settings.admin_ip_allowlist)
    except ValueError:
        return False


async def create_admin(s: AsyncSession, settings: Settings, telegram_id: int, role: str, password: str) -> str:
    """Returns the TOTP provisioning URI (shown ONCE). Refuses IDs outside the env allowlist."""
    if telegram_id not in settings.admin_allowlist_ids:
        raise AuthError("telegram id not in ADMIN_ALLOWLIST")
    if role not in ROLES:
        raise AuthError("unknown role")
    if len(password) < 12:
        raise AuthError("password must be at least 12 characters")
    secret = pyotp.random_base32()
    s.add(AdminUser(telegram_id=telegram_id, role=role, password_hash=hash_password(password),
                    totp_secret_enc=encrypt_secret(settings, secret)))
    await s.flush()
    await append_audit(s, settings, "system", "admin.created", "admin", telegram_id, {"role": role})
    return pyotp.TOTP(secret).provisioning_uri(name=str(telegram_id), issuer_name="FootballBotAdmin")


async def login(s: AsyncSession, settings: Settings, telegram_id: int, password: str, totp: str, ip: str | None
                ) -> str:
    """Returns an opaque session token. Every failure mode returns the same error to the caller."""
    deny = AuthError("invalid credentials")
    now = utcnow()
    if telegram_id not in settings.admin_allowlist_ids or not ip_allowed(settings, ip):
        await security_event(s, "admin_login_denied_allowlist", "high", actor=str(telegram_id), ip=ip)
        raise deny
    a = await s.get(AdminUser, telegram_id)
    if a is None or not a.active:
        await security_event(s, "admin_login_unknown", "warn", actor=str(telegram_id), ip=ip)
        raise deny
    if a.locked_until and a.locked_until > now:
        raise deny
    totp_obj = pyotp.TOTP(decrypt_secret(settings, a.totp_secret_enc))
    step = int(now.timestamp() // 30)
    ok = (verify_password(password, a.password_hash) and totp.isdigit() and len(totp) == 6
          and totp_obj.verify(totp, valid_window=1) and step > a.last_totp_step)
    if not ok:
        a.failed_attempts += 1
        if a.failed_attempts >= MAX_FAILS:
            a.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            a.failed_attempts = 0
            await security_event(s, "admin_locked", "high", actor=str(telegram_id), ip=ip)
        await security_event(s, "admin_login_failed", "warn", actor=str(telegram_id), ip=ip)
        raise deny
    a.failed_attempts, a.last_totp_step, a.totp_enrolled = 0, step, True   # the same code can't be reused
    tok = new_token()
    s.add(AdminSession(token_hash=sha256_hex(tok), admin_id=telegram_id, ip=ip,
                       expires_at=now + timedelta(seconds=settings.admin_session_ttl_seconds)))
    await append_audit(s, settings, f"admin:{telegram_id}", "admin.login", "admin", telegram_id, {"ip": ip})
    return tok


async def authenticate(s: AsyncSession, settings: Settings, token: str | None, ip: str | None) -> AdminUser:
    if not token or not ip_allowed(settings, ip):
        raise AuthError("unauthorized")
    sess = await s.get(AdminSession, sha256_hex(token))
    now = utcnow()
    if sess is None or sess.revoked or sess.expires_at <= now:
        raise AuthError("unauthorized")
    a = await s.get(AdminUser, sess.admin_id)
    if a is None or not a.active or a.telegram_id not in settings.admin_allowlist_ids:
        raise AuthError("unauthorized")
    return a


async def require(s: AsyncSession, settings: Settings, token: str | None, ip: str | None, perm: str) -> AdminUser:
    a = await authenticate(s, settings, token, ip)
    if not has_perm(a.role, perm):
        await security_event(s, "admin_permission_denied", "warn", actor=str(a.telegram_id), perm=perm)
        raise AuthError("forbidden")
    return a
