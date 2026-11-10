"""Crypto helpers: canonical JSON, HMACs, password hashing, secret encryption, security events."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import SecurityEvent

log = logging.getLogger("security")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _key(secret: str, name: str) -> bytes:
    if len(secret) < 16:
        raise RuntimeError(f"{name} is not configured (min 16 chars; 32+ random bytes in prod)")
    return secret.encode()


def hmac_hex(secret: str, data: str, name: str = "key") -> str:
    return hmac.new(_key(secret, name), data.encode(), hashlib.sha256).hexdigest()


def hmac_ok(secret: str, data: str, signature: str, name: str = "key") -> bool:
    return hmac.compare_digest(hmac_hex(secret, data, name), signature)


def fernet(settings: Settings) -> Fernet:
    return Fernet(settings.secrets_key.get_secret_value().encode())


def encrypt_secret(settings: Settings, plaintext: str) -> str:
    return fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt_secret(settings: Settings, token: str) -> str:
    try:
        return fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("cannot decrypt secret (wrong SECRETS_KEY?)") from e


# --- passwords: scrypt (stdlib, memory-hard) ----------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        salt, want = base64.b64decode(s), base64.b64decode(h)
    except Exception:
        return False
    got = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got, want)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


async def security_event(session: AsyncSession, kind: str, severity: str = "warn",
                         actor: str | None = None, **data: Any) -> None:
    """Persist + log a security event. Callers must never pass secrets in `data`."""
    session.add(SecurityEvent(kind=kind, severity=severity, actor=actor, data=data))
    log.warning("security_event", extra={"kind": kind, "severity": severity, "actor": actor})
