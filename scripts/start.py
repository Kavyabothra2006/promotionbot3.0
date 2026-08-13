from __future__ import annotations

import asyncio
import os
import subprocess
import sys


def main() -> None:
    env = os.environ.copy()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    from app.main import main as bot_main
    asyncio.run(bot_main())


if __name__ == "__main__":
    main()
