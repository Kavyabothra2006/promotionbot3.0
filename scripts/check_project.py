from __future__ import annotations

import compileall
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ok = compileall.compile_dir(str(root / "app"), quiet=1)
    if not ok:
        raise SystemExit("Python compilation failed")
    print("Python compilation: PASS")
    required = [root / ".env.testing.example", root / "pytest.ini", root / "scripts" / "test_ready_check.py", root / "scripts" / "staging_start.py"]
    if not all(path.exists() for path in required):
        raise SystemExit("Testing/staging support files are incomplete")
    print("Testing/staging support: PASS")
    print("Next: copy .env.testing.example to .env, run scripts/test_ready_check.py, alembic upgrade head, pytest -q, then scripts/staging_start.py.")


if __name__ == "__main__":
    main()
