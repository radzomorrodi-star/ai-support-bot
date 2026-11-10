"""Signed, versioned operator configuration. Fails CLOSED on a bad signature (no pricing/betting)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import SignedConfig
from app.security import canonical, hmac_ok, hmac_hex, security_event
from app.services.audit import append_audit

DEFAULT_CONFIG: dict[str, Any] = {
    "margin_bp": 500,                 # 5.00% applied to fair probabilities
    "min_quotes": 3,                  # min distinct valid bookmakers per outcome
    "max_quote_age_s": 900,           # bookmaker quote older than this is stale
    "quote_ttl_s": 120,               # how long a customer's pending bet draft stays confirmable
    "price_valid_s": 1200,            # how long a published price snapshot may be shown/accepted
    "bet_cutoff_s": 60,               # stop accepting this long before kickoff
    "min_stake_minor": 100,
    "max_stake_minor": 100_000,
    "default_daily_limit_minor": 500_000,
    "demo_initial_balance_minor": 100_000,
    "terms_version": "1.0",
    "claim_window_days": 10,
    "claim_reminder_days_before": [3, 1],
    "mkt_overround_min_bp": 9800,     # median market overround sanity band (sum of implied probs)
    "mkt_overround_max_bp": 15000,
    "cust_overround_min_bp": 10100,
    "cust_overround_max_bp": 13500,
    "blocked_countries": [],
    "compliance": {"license_ref": "", "legal_approval_ref": "", "security_assessment_ref": "",
                   "approved_jurisdictions": []},
    # canonical bookmaker -> provider keys (CANDIDATES; actual availability is detected at runtime)
    "bookmaker_aliases": {
        "bet365": ["bet365"],
        "pinnacle": ["pinnacle"],
        "betfair": ["betfair_ex_eu", "betfair_ex_uk", "betfair_sb_uk", "betfair"],
        "bwin": ["bwin"],
        "unibet": ["unibet_eu", "unibet_uk", "unibet_fr", "unibet_it", "unibet_nl", "unibet_se", "unibet"],
        "williamhill": ["williamhill", "william_hill"],
        "betano": ["betano", "betano_uk"],
        "888sport": ["sport888", "888sport"],
        "betway": ["betway"],
        "marathonbet": ["marathonbet"],
    },
}

BOUNDS = {"margin_bp": (0, 2000), "min_quotes": (1, 10), "quote_ttl_s": (10, 600), "bet_cutoff_s": (0, 3600),
          "claim_window_days": (1, 90)}


class ConfigTampered(RuntimeError):
    pass


class ConfigInvalid(ValueError):
    pass


def validate(cfg: dict[str, Any]) -> None:
    missing = set(DEFAULT_CONFIG) - set(cfg)
    if missing:
        raise ConfigInvalid(f"missing keys: {sorted(missing)}")
    for k, (lo, hi) in BOUNDS.items():
        if not isinstance(cfg[k], int) or isinstance(cfg[k], bool) or not lo <= cfg[k] <= hi:
            raise ConfigInvalid(f"{k} must be an int in [{lo}, {hi}]")
    if not 0 < cfg["min_stake_minor"] <= cfg["max_stake_minor"]:
        raise ConfigInvalid("stake bounds invalid")


def _sig_material(version: int, payload: dict) -> str:
    return canonical({"version": version, "payload": payload})


async def _latest_version(session: AsyncSession) -> int:
    return (await session.execute(select(func.max(SignedConfig.version)))).scalar() or 0


async def publish(session: AsyncSession, settings: Settings, payload: dict[str, Any], actor: str,
                  reason: str) -> SignedConfig:
    """Append a new signed version. Never edits an existing row. Always audited."""
    validate(payload)
    version = await _latest_version(session) + 1
    material = _sig_material(version, payload)
    row = SignedConfig(version=version, payload=deepcopy(payload), payload_canonical=material,
                       signature=hmac_hex(settings.config_signing_key.get_secret_value(), material, "CONFIG_SIGNING_KEY"),
                       created_by=actor, reason=reason[:300])
    session.add(row)
    await session.flush()
    await append_audit(session, settings, actor, "config.publish", "signed_config", version,
                       {"reason": reason[:300], "margin_bp": payload["margin_bp"]})
    return row


async def ensure_initial(session: AsyncSession, settings: Settings) -> None:
    if await _latest_version(session) == 0:
        await publish(session, settings, DEFAULT_CONFIG, "system", "initial defaults")


async def load_active(session: AsyncSession, settings: Settings) -> tuple[int, dict[str, Any]]:
    """Latest version, signature-verified. Raises ConfigTampered (and records an event) otherwise."""
    row = (await session.execute(select(SignedConfig).order_by(SignedConfig.version.desc()).limit(1))).scalar()
    if row is None:
        raise ConfigTampered("no signed configuration present")
    ok = (row.payload_canonical == _sig_material(row.version, row.payload)
          and hmac_ok(settings.config_signing_key.get_secret_value(), row.payload_canonical, row.signature,
                      "CONFIG_SIGNING_KEY"))
    if not ok:
        await security_event(session, "config_signature_invalid", "critical", version=row.version)
        await session.commit()
        raise ConfigTampered(f"configuration v{row.version} failed signature verification")
    return row.version, row.payload
