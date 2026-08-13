from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("PASTE_") or value.startswith("replace_"):
        raise RuntimeError(f"{name} is not configured for testing")
    return value


async def _check_services() -> None:
    from aiogram import Bot
    from redis.asyncio import Redis
    from sqlalchemy import text

    from app.config import settings
    from app.database.base import engine

    bot_token = _require_env("BOT_TOKEN")
    _require_env("DATABASE_URL")
    _require_env("REDIS_URL")

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    bot = Bot(token=bot_token)
    try:
        await redis.ping()
        me = await bot.get_me()
        print(f"Telegram API: PASS (@{me.username or me.id})")
        print("PostgreSQL: PASS")
        print("Redis: PASS")
    finally:
        await bot.session.close()
        await redis.aclose()


def main() -> None:
    try:
        asyncio.run(_check_services())
    except Exception as exc:
        print(f"TEST ENVIRONMENT: FAIL - {exc}")
        raise SystemExit(1) from exc
    print("TEST ENVIRONMENT: PASS")
    print("Next: run `alembic upgrade head` and then `pytest -q`.")


if __name__ == "__main__":
    main()
