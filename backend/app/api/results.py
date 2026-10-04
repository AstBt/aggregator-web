# -*- coding: utf-8 -*-
"""结果 API：订阅列表/详情、节点列表/详情/导出、CSV 导出。"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import Node, Subscription, User
from services import export_service

router = APIRouter(tags=["results"])


# ---------- 订阅 ----------
@router.get("/api/subscriptions")
def list_subscriptions(
    status_: str | None = Query(None, alias="status"),
    origin: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Subscription)
    if status_:
        stmt = stmt.where(Subscription.status == status_)
    if origin:
        stmt = stmt.where(Subscription.origin == origin)
    if keyword:
        stmt = stmt.where(Subscription.url.like(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Subscription.id).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for row in rows:
        contributed = db.scalar(
            select(func.count(func.distinct(Node.id))).where(Node.source_sub == row.url, Node.alive.is_(True))
        )
        items.append(_subscription_item(row, contributed or 0))
    return {"total": total, "items": items}


@router.get("/api/subscriptions/{sub_id}")
def subscription_detail(
    sub_id: int,
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(Subscription, sub_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订阅不存在")
    contributed = db.scalar(
        select(func.count(func.distinct(Node.id))).where(Node.source_sub == row.url, Node.alive.is_(True))
    )
    return _subscription_item(row, contributed or 0, detail=True)


def _subscription_item(row: Subscription, contributed: int, detail: bool = False) -> dict:
    item = {
        "id": row.id,
        "url": row.url,
        "origin": row.origin,
        "status": row.status,
        "errors": row.errors,
        "discovered": row.discovered,
        "skip_cache": row.skip_cache,
        "allow_nonstandard": row.allow_nonstandard,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "last_alive_at": row.last_alive_at.isoformat() if row.last_alive_at else None,
        "contributed_nodes": contributed,
    }
    return item


# ---------- 节点 ----------
def _node_item(row: Node) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "protocol": row.protocol,
        "server": row.server,
        "port": row.port,
        "source_sub": row.source_sub,
        "delay_ms": row.delay_ms,
        "region": row.region,
        "residential": row.residential,
        "alive": row.alive,
        "run_id": row.run_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/api/nodes")
def list_nodes(
    protocol: str | None = None,
    region: str | None = None,
    alive: bool | None = None,
    residential: bool | None = None,
    min_delay: int | None = None,
    max_delay: int | None = None,
    keyword: str | None = None,
    run_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Node)
    if protocol:
        stmt = stmt.where(Node.protocol == protocol)
    if region:
        stmt = stmt.where(Node.region == region)
    if alive is not None:
        stmt = stmt.where(Node.alive == alive)
    if residential is not None:
        stmt = stmt.where(Node.residential == residential)
    if min_delay is not None:
        stmt = stmt.where(Node.delay_ms >= min_delay)
    if max_delay is not None:
        stmt = stmt.where(Node.delay_ms <= max_delay)
    if keyword:
        stmt = stmt.where(Node.name.like(f"%{keyword}%"))
    if run_id is not None:
        stmt = stmt.where(Node.run_id == run_id)
    else:
        latest = db.scalar(select(func.max(Node.run_id)))
        if latest:
            stmt = stmt.where(Node.run_id == latest)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Node.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [_node_item(r) for r in rows]}


@router.get("/api/nodes/{node_id}")
def node_detail(
    node_id: int,
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(Node, node_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节点不存在")
    return {**_node_item(row), "raw": row.raw}


class ExportIn(BaseModel):
    target: str
    run_id: int | None = None
    only_alive: bool = True
    protocols: list[str] | None = None


@router.post("/api/nodes/export")
def export_nodes(
    body: ExportIn,
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    """按客户端类型导出（FR-5.5）：默认仅存活节点。"""
    if body.target not in export_service.TARGETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的客户端类型: {body.target}")
    stmt = select(Node)
    if body.only_alive:
        stmt = stmt.where(Node.alive.is_(True))
    if body.protocols:
        stmt = stmt.where(Node.protocol.in_(body.protocols))
    if body.run_id is not None:
        stmt = stmt.where(Node.run_id == body.run_id)
    rows = db.scalars(stmt.order_by(Node.id)).all()
    nodes = [{**_node_item(r), "raw": r.raw} for r in rows]
    limit = export_service.node_limit(db)
    if limit > 0 and len(nodes) > limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"节点数 {len(nodes)} 超过导出上限 {limit}，请缩小范围"
        )
    try:
        content = export_service.build(body.target, nodes)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "target": body.target,
        "count": len(nodes),
        "content": content,
        "filename": export_service.TARGETS and {"clash": "clash.yaml", "v2ray": "v2ray.txt", "singbox": "singbox.json"}[body.target],
    }


@router.get("/api/export/subscriptions.csv")
def export_subscriptions_csv(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Subscription).order_by(Subscription.id)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "url", "origin", "status", "errors", "first_seen_at", "last_alive_at"])
    for row in rows:
        writer.writerow([row.id, row.url, row.origin, row.status, row.errors, row.first_seen_at, row.last_alive_at])
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(buffer.getvalue(), media_type="text/csv; charset=utf-8")


@router.get("/api/export/nodes.csv")
def export_nodes_csv(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Node).order_by(Node.id)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "name", "protocol", "server", "port", "region", "delay_ms", "alive", "source_sub"])
    for row in rows:
        writer.writerow([row.id, row.name, row.protocol, row.server, row.port, row.region, row.delay_ms, row.alive, row.source_sub])
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(buffer.getvalue(), media_type="text/csv; charset=utf-8")
