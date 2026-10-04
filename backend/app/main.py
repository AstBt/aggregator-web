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
    from engine_adapter.engine import RealEngine
    from engine_adapter.runner import TaskRunner
    from seed import init_db

    init_db()
    TaskRunner.instance().engine = RealEngine()  # 生产引擎：复用 subscribe/
    yield


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

    from api import auth, dashboard, params, results, sources, storage, tasks, users

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(sources.router)
    app.include_router(params.router)
    app.include_router(tasks.router)
    app.include_router(results.router)
    app.include_router(storage.router)
    app.include_router(dashboard.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"code": 0, "data": {"status": "up"}, "message": "ok"}

    if settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")

    return app


app = create_app()
