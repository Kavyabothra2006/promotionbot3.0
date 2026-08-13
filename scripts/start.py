from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    # Project root: /app when deployed on Railway
    project_root = Path(__file__).resolve().parent.parent

    # Make the project root importable so `from app...` works
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Make sure subprocesses also see the project root.
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(project_root)
        if not current_pythonpath
        else str(project_root) + os.pathsep + current_pythonpath
    )

    # Run database migrations before starting the bot.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=str(project_root),
        env=env,
    )

    # Import only after the project root has been added to sys.path.
    from app.main import main as bot_main

    asyncio.run(bot_main())


if __name__ == "__main__":
    main()
