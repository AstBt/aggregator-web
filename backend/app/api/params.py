# -*- coding: utf-8 -*-
"""参数配置 API：爬取参数 / 验活参数 / 测试连接（FR-3.9~3.16, A6/A7）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import User
from schemas import AliveParamsPatch, CrawlParamsPatch
from services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class TestUrlIn(BaseModel):
    url: str


# ---------- 爬取参数 ----------
@router.get("/crawl")
def read_crawl(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    return settings_service.get_crawl(db)


@router.put("/crawl")
def write_crawl(
    payload: CrawlParamsPatch,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    return settings_service.put_crawl(db, payload.model_dump(exclude_none=True))


@router.post("/crawl/proxy/test")
def test_proxy(
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    return settings_service.probe_via_proxy(db)


# ---------- 验活参数 ----------
@router.get("/alive")
def read_alive(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    return settings_service.get_alive(db)


@router.put("/alive")
def write_alive(
    payload: AliveParamsPatch,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return settings_service.put_alive(db, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/alive/test-urls")
def add_test_url(
    body: TestUrlIn,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> list[str]:
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请输入合法的 http(s) 地址")
    current = settings_service.get_alive(db)
    urls = list(current.get("test_urls") or [])
    if url not in urls:
        urls.append(url)
    try:
        saved = settings_service.put_alive(db, {"test_urls": urls})
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return saved["test_urls"]


@router.delete("/alive/test-urls")
def remove_test_url(
    url: str = Query(...),
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> list[str]:
    current = settings_service.get_alive(db)
    urls = [u for u in (current.get("test_urls") or []) if u != url]
    try:
        saved = settings_service.put_alive(db, {"test_urls": urls})
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return saved["test_urls"]


@router.post("/alive/test-url")
def test_url(
    url: str = Query(...),
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    """页面连通性测试：经本地代理（如启用）；实际节点验活直连（FR-3.14a）。"""
    crawl = settings_service.get_crawl(db)
    proxy = ""
    proxy_cfg = crawl.get("proxy") or {}
    if proxy_cfg.get("enable") and proxy_cfg.get("address"):
        proxy = proxy_cfg["address"]
    return settings_service.probe_url(url, proxy=proxy)
