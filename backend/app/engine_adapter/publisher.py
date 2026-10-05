# -*- coding: utf-8 -*-
"""发布器：本地/远端存储目标写入（准原子）+ 补偿重试（FR-4.10 / FR-5.14, A16）。"""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy.orm import Session

from models import StorageTarget, WriteLog

FILENAMES = {"clash": "clash.yaml", "v2ray": "v2ray.txt", "singbox": "singbox.json"}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf8") as f:
        return f.read()


def _write_file(path: str, content: str) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as f:
        f.write(content)
    return os.path.getsize(path)


def _push_remote(target: StorageTarget, specs: list[dict], group: str) -> dict:
    """远端目标：复用 subscribe/push 的既有实现（gist / pastegg / pastefy / imperial / qbin）。"""
    from config.models import StorageConfig, StorageItem
    from engine_adapter.registry import ensure_engine_on_path

    ensure_engine_on_path()
    import push as push_module
    from services import storage_service

    token = storage_service.decrypt_token(target.token_ref or "")
    config = dict(target.config or {})
    storage = StorageConfig(
        engine=target.type,
        token=token,
        base=config.get("base", ""),
        domain=config.get("domain", ""),
        items={},
    )
    tool = push_module.get_instance(storage)
    written = 0
    for spec in specs:
        content = _read(spec["path"])
        if not content.strip():
            continue  # 空产物不推送（与引擎层空内容保护一致）
        item = StorageItem(
            gist_id=config.get("gist_id", ""),
            filename=os.path.basename(spec["path"]),
            folder_id=config.get("folder_id", ""),
            file_id=config.get("file_id", "") or os.path.basename(spec["path"]),
        )
        if tool.push_to(content=content, item=item, group=group):
            written += 1
        else:
            raise ValueError(f"远端写入失败: {os.path.basename(spec['path'])}")
    return {"ok": True, "written": written}


def _write_target(session: Session, run_id: int, target: StorageTarget, artifacts: list[dict]) -> dict:
    """写入单个目标；成功返回 ok，失败返回错误（不抛异常，隔离单目标故障）。"""
    try:
        if target.type == "local":
            directory = str((target.config or {}).get("dir") or "")
            if not directory:
                raise ValueError("本地目标未配置目录")
            written = 0
            for spec in artifacts:
                content = _read(spec["path"])
                if not content.strip():
                    continue
                _write_file(os.path.join(directory, os.path.basename(spec["path"])), content)
                written += 1
            size = written
        else:
            result = _push_remote(target, artifacts, group=f"run-{run_id}")
            size = result["written"]
        target.last_write_at = datetime.now()
        target.last_write_ok = True
        target.last_write_error = None
        session.add(WriteLog(run_id=run_id, target_id=target.id, kind="artifact", target_type=target.type, ok=True, size=size))
        session.commit()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 — 单目标失败隔离
        target.last_write_at = datetime.now()
        target.last_write_ok = False
        target.last_write_error = str(exc)
        session.add(WriteLog(run_id=run_id, target_id=target.id, kind="artifact", target_type=target.type, ok=False, error=str(exc)))
        session.commit()
        return {"ok": False, "error": str(exc)}


def publish(session: Session, run_id: int, artifacts: list[dict], target_ids: list[int]) -> list[int]:
    """准原子发布：全部目标成功返回空 pending 列表；否则返回待补偿目标 id 列表。"""
    pending: list[int] = []
    for target_id in target_ids:
        target = session.get(StorageTarget, target_id)
        if target is None or not target.enable:
            continue
        result = _write_target(session, run_id, target, artifacts)
        if not result["ok"]:
            pending.append(target_id)
    return pending


def retry_publish(session: Session, run_id: int, target_ids: list[int] | None = None) -> dict:
    """补偿发布：对失败（或指定）目标重放本轮 artifacts（FR-4.10）。"""
    from models import Artifact, CrawlRun

    run = session.get(CrawlRun, run_id)
    if run is None:
        raise ValueError("任务不存在")
    artifacts = [
        {"target": a.target, "path": a.path, "size": a.size}
        for a in session.query(Artifact).filter_by(run_id=run_id).all()
    ]
    if not artifacts:
        raise ValueError("本轮无可重放产物")
    pending = list(run.publish_pending or [])
    if target_ids:
        pending = [tid for tid in pending if tid in target_ids] or list(target_ids)
    if not pending:
        return {"retried": 0, "remaining": 0, "ok": True}

    still: list[int] = []
    for target_id in pending:
        target = session.get(StorageTarget, target_id)
        if target is None:
            continue
        result = _write_target(session, run_id, target, artifacts)
        if result["ok"]:
            target.last_write_error = None
            session.query(WriteLog).filter_by(run_id=run_id, target_id=target_id, ok=False).update({"replayed": True})
        else:
            still.append(target_id)
    run.publish_pending = still or None
    if not still:
        run.status = "success"
    session.commit()
    return {"retried": len(pending) - len(still), "remaining": still, "ok": not still}
