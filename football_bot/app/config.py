"""Environment-driven settings. Secrets are SecretStr and are never logged."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str | None = None  # None -> in-process fallback (dev/test only)

    bot_token: SecretStr | None = None
    telegram_mode: Literal["polling", "webhook"] = "polling"
    webhook_base_url: str = ""
    webhook_secret_token: SecretStr = SecretStr("")
    webhook_path_secret: SecretStr = SecretStr("")

    secrets_key: SecretStr = SecretStr("")        # Fernet key (encrypts TOTP secrets)
    receipt_hmac_key: SecretStr = SecretStr("")
    config_signing_key: SecretStr = SecretStr("")
    audit_hmac_key: SecretStr = SecretStr("")

    admin_allowlist: CsvList = []
    admin_ip_allowlist: CsvList = []
    admin_session_ttl_seconds: int = 1800

    odds_primary_provider: str = "mock"
    odds_fallback_provider: str = ""
    the_odds_api_key: SecretStr | None = None
    odds_regions: str = "eu,uk"
    odds_http_timeout_seconds: float = 10.0
    odds_refresh_seconds: int = 900

    real_money_enabled: bool = False
    default_timezone: str = "Asia/Tehran"

    @field_validator("admin_allowlist", "admin_ip_allowlist", mode="before")
    @classmethod
    def _csv(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def admin_allowlist_ids(self) -> set[int]:
        return {int(x) for x in self.admin_allowlist}

    def require_prod_secrets(self) -> None:
        """Fail closed in prod if any key is missing or weak."""
        if self.environment != "prod":
            return
        if self.database_url.startswith("sqlite"):
            raise RuntimeError("SQLite is not allowed in prod; use PostgreSQL")
        if self.real_money_enabled:
            raise RuntimeError("REAL_MONEY_ENABLED must stay false: this build is demo-only")
        missing = [
            n for n in ("secrets_key", "receipt_hmac_key", "config_signing_key", "audit_hmac_key")
            if len(getattr(self, n).get_secret_value()) < 32
        ]
        if missing:
            raise RuntimeError(f"Missing/weak secrets in prod: {', '.join(missing)}")
        if self.telegram_mode == "webhook" and (
            len(self.webhook_secret_token.get_secret_value()) < 32
            or len(self.webhook_path_secret.get_secret_value()) < 32
        ):
            raise RuntimeError("Webhook secrets missing/weak")


@lru_cache
def get_settings() -> Settings:
    return Settings()
