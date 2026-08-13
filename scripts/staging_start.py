from __future__ import annotations

import asyncio
import os
import subprocess
import sys


def main() -> None:
    environment = os.getenv("ENVIRONMENT", "testing").lower()
    if environment not in {"testing", "test", "staging"}:
        raise SystemExit("staging_start.py requires ENVIRONMENT=testing, test, or staging")

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    from app.main import main as bot_main
    asyncio.run(bot_main())


if __name__ == "__main__":
    main()
