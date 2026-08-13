from __future__ import annotations

from functools import lru_cache

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import NoDecode
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    value = url.strip()
    if value.startswith("postgres://"):
        value = "postgresql+asyncpg://" + value[len("postgres://") :]
    elif value.startswith("postgresql://"):
        value = "postgresql+asyncpg://" + value[len("postgresql://") :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    SUPER_ADMIN_IDS: Annotated[list[int], NoDecode] = Field(default_factory=list)
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    THROTTLE_RATE_LIMIT: float = 0.7
    DEFAULT_REFERRAL_TARGET: int = 2
    INVITE_EXPIRY_HOURS: int = 48
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800
    PROCESSED_UPDATE_RETENTION_DAYS: int = 14
    IDEMPOTENCY_LOCK_SECONDS: int = 3600

    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "production"

    @field_validator("SUPER_ADMIN_IDS", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> list[int]:
        if isinstance(v, str):
            try:
                return [int(x.strip()) for x in v.split(",") if x.strip()]
            except ValueError as exc:
                raise ValueError("SUPER_ADMIN_IDS must be comma-separated Telegram numeric IDs") from exc
        if isinstance(v, list):
            return [int(x) for x in v]
        return []

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _validate_database_url(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("DATABASE_URL is required")
        value = _normalize_database_url(v)
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use PostgreSQL with asyncpg")
        return value

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        if not self.BOT_TOKEN.strip():
            raise ValueError("BOT_TOKEN is required")
        if self.THROTTLE_RATE_LIMIT <= 0:
            raise ValueError("THROTTLE_RATE_LIMIT must be > 0")
        if not 1 <= self.DEFAULT_REFERRAL_TARGET <= 10:
            raise ValueError("DEFAULT_REFERRAL_TARGET must be between 1 and 10")
        if self.INVITE_EXPIRY_HOURS < 1:
            raise ValueError("INVITE_EXPIRY_HOURS must be >= 1")
        if self.DB_POOL_SIZE < 1 or self.DB_MAX_OVERFLOW < 0 or self.DB_POOL_RECYCLE < 60:
            raise ValueError("Invalid PostgreSQL pool settings")
        if self.PROCESSED_UPDATE_RETENTION_DAYS < 1:
            raise ValueError("PROCESSED_UPDATE_RETENTION_DAYS must be >= 1")
        if self.IDEMPOTENCY_LOCK_SECONDS < 300:
            raise ValueError("IDEMPOTENCY_LOCK_SECONDS must be >= 300")
        if self.ENVIRONMENT.lower() in {"production", "prod"} and self.BOT_TOKEN.startswith("123456789:"):
            raise ValueError("Replace the example BOT_TOKEN before production startup")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
