from __future__ import annotations

from app.main import main


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    import asyncio
    asyncio.run(main())
