# -*- coding: utf-8 -*-
"""爬取源 API（FR-3.1~3.8, A4/A5）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import CrawlSource, User
from schemas import Page, SourceCreate, SourceItem, SourceUpdate
from services import source_schema, sources_service

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/schema")
def source_schema_api(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    """爬取源配置 Schema（字段/示例/条件/校验规则的单一事实源，前端动态渲染表单）。"""
    from engine_adapter.registry import plugin_names

    return {"ok": True, "schemas": source_schema.all_schemas(plugin_names())}


@router.get("", response_model=Page)
def list_sources(
    type: str | None = None,
    enable: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> Page:
    stmt = select(CrawlSource)
    if type:
        stmt = stmt.where(CrawlSource.type == type)
    if enable is not None:
        stmt = stmt.where(CrawlSource.enable == enable)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(CrawlSource.id).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(total=total, items=[SourceItem.model_validate(s) for s in items])


@router.post("", response_model=SourceItem, status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceCreate,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> SourceItem:
    _validate(body.type, body.config)
    if db.query(CrawlSource).filter_by(name=body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "源名称已存在")
    source = CrawlSource(type=body.type, name=body.name, config=body.config)
    db.add(source)
    db.commit()
    db.refresh(source)
    return SourceItem.model_validate(source)


@router.put("/{source_id}", response_model=SourceItem)
def update_source(
    source_id: int,
    body: SourceUpdate,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> SourceItem:
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "源不存在")
    if body.config is not None:
        _validate(source.type, body.config)
        source.config = body.config
    if body.enable is not None:
        source.enable = body.enable
    db.commit()
    db.refresh(source)
    return SourceItem.model_validate(source)


@router.delete("/{source_id}")
def delete_source(
    source_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "源不存在")
    db.delete(source)
    db.commit()
    return {"ok": True}


@router.post("/{source_id}/toggle", response_model=SourceItem)
def toggle_source(
    source_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> SourceItem:
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "源不存在")
    source.enable = not source.enable
    db.commit()
    db.refresh(source)
    return SourceItem.model_validate(source)


@router.post("/{source_id}/test")
def test_source(
    source_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    """固定外部请求探测（测试连接子组件，FR-3.6）。"""
    source = db.get(CrawlSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "源不存在")
    if source.type == "script":
        from engine_adapter.registry import plugin_exists

        ok = plugin_exists(str(source.config.get("plugin", "")))
        return {"ok": ok, "detail": "插件已注册" if ok else "插件未注册"}
    url = sources_service.source_first_url(source.config)
    if not url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该类型源不支持连通性测试（无可探测 URL）")
    result = sources_service.probe_url(url)
    return {"ok": result["ok"], "status": result.get("status"), "cost_ms": result.get("cost_ms")}


@router.get("/export")
def export_sources(
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    sources = db.scalars(select(CrawlSource)).all()
    return sources_service.to_export_payload(sources)


@router.post("/import")
def import_sources(
    payload: dict,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    created = merged = 0
    for item in sources_service.from_import_payload(payload):
        if sources_service.validate_source_config(item["type"], item["config"]):
            continue
        existing = db.query(CrawlSource).filter_by(name=item["name"]).first()
        if existing:
            existing.config = item["config"]
            merged += 1
        else:
            db.add(CrawlSource(type=item["type"], name=item["name"], config=item["config"]))
            created += 1
    db.commit()
    return {"created": created, "merged": merged}


def _validate(source_type: str, config: dict) -> None:
    errors = sources_service.validate_source_config(source_type, config)
    if errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "；".join(errors))
