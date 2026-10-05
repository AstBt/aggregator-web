# -*- coding: utf-8 -*-
"""Web 平台启动入口：python backend/run.py（单进程：API + 前端静态托管）。"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def main() -> None:
    import uvicorn

    from settings import settings

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        app_dir=str(APP_DIR),
    )


if __name__ == "__main__":
    main()
