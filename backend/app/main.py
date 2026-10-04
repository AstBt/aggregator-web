# -*- coding: utf-8 -*-
"""FastAPI 应用工厂。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    import os

    from engine_adapter.runner import HermeticEngine, TaskRunner
    from engine_adapter.scheduler import SchedulerHub
    from seed import init_db

    init_db()
    SchedulerHub.instance().start()  # FR-4.8：APScheduler 到点为启用 schedule 生成 run
    if os.environ.get("AGG_ENGINE") == "hermetic":
        # E2E/演示钩子：确定性引擎，避免真实网络依赖
        TaskRunner.instance().engine = HermeticEngine(
            subscriptions=[("https://e2e.example.com/link/abc?sub=3", "TELEGRAM", True)],
            proxies=[
                {"name": "🚀 香港01", "type": "vless", "server": "hk01.example.com", "port": 443,
                 "uuid": "e5f3-a91c", "network": "ws", "tls": True, "delay": 180},
                {"name": "🚀 新加坡02", "type": "vmess", "server": "sg02.example.net", "port": 80,
                 "uuid": "7b2c-11f0", "alterId": 0, "delay": 460},
                {"name": "🚀 香港04", "type": "hysteria2", "server": "hk04.example.io", "port": 36712,
                 "password": "s3cret", "sni": "hk04.example.io", "delay": 167},
            ],
        )
    else:
        from engine_adapter.engine import RealEngine

        TaskRunner.instance().engine = RealEngine()  # 生产引擎：复用 subscribe/
    yield
    SchedulerHub.instance().stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Aggregator Web 管理平台", version="2.4.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def envelope(request: Request, call_next) -> Response:
        """统一响应包 {code, data, message}。"""
        response = await call_next(request)
        if request.url.path.startswith("/api") and "application/json" in response.headers.get(
            "content-type", ""
        ):
            body = b"".join([section async for section in response.body_iterator])
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = None
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            if isinstance(data, dict) and {"code", "data", "message"} == set(data):
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type="application/json",
                )
            code = 0 if response.status_code < 400 else response.status_code
            message = data.get("detail", "") if isinstance(data, dict) else str(data)
            payload = data if code == 0 and data is not None else None
            return JSONResponse(
                {"code": code, "data": payload, "message": message},
                status_code=response.status_code,
                headers=headers,
            )
        return response

    from api import auth, dashboard, params, results, schedules, sources, storage, tasks, users

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(sources.router)
    app.include_router(params.router)
    app.include_router(tasks.router)
    app.include_router(results.router)
    app.include_router(storage.router)
    app.include_router(schedules.router)
    app.include_router(dashboard.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"code": 0, "data": {"status": "up"}, "message": "ok"}

    if settings.frontend_dist.is_dir():
        from fastapi.responses import FileResponse

        index_file = settings.frontend_dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):  # noqa: ANN001
            """SPA 托管：静态文件优先，未命中回退 index.html。"""
            candidate = (settings.frontend_dist / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(settings.frontend_dist.resolve())):
                return FileResponse(candidate)
            return FileResponse(index_file)

    return app


app = create_app()
