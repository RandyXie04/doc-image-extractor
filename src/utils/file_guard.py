# -*- coding: utf-8 -*-
"""
File Guard & Ephemeral Lifecycle Utilities
- MaxBodySizeMiddleware: ASGI middleware early-checking Content-Length header before multipart parser writes to tempfile.
- save_upload_file_safely: Streaming chunk reader with exact byte accumulation to abort and delete partial files.
- purge_expired_files: 24-hour retention janitor safely unlinking expired files while bypassing active tasks.
- purge_in_memory_records: In-memory task tracker expiration to prevent state memory leaks.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Set, Optional

from fastapi import UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

CHUNK_SIZE = 64 * 1024  # 64 KB


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """
    第一道防線：在 Starlette 解析 Multipart 寫入 SpooledTemporaryFile 之前，
    先攔截檢查 Content-Length，防止巨型上傳耗盡伺服器系統槽 (C:\\Temp)。
    """
    def __init__(self, app, max_upload_bytes: int, max_template_bytes: Optional[int] = None):
        super().__init__(app)
        self.max_upload_bytes = max_upload_bytes
        self.max_template_bytes = max_template_bytes or (20 * 1024 * 1024)

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    length_val = int(content_length)
                    limit = self.max_template_bytes if request.url.path == "/api/upload_template" else self.max_upload_bytes
                    if length_val > limit:
                        limit_mb = limit // (1024 * 1024)
                        return JSONResponse(
                            status_code=413,
                            content={"detail": f"上傳請求超過單次大小限制 (上限 {limit_mb} MB)"}
                        )
                except ValueError:
                    pass
        return await call_next(request)


async def save_upload_file_safely(
    upload_file: UploadFile,
    destination: Path,
    max_mb: int = 200
) -> int:
    """
    第二道防線：以 64KB 串流分塊寫入目標路徑，精準計算實際位元組。
    一旦超標立即中斷、關閉控制代碼並刪除殘留半成品檔案。
    """
    max_bytes = max_mb * 1024 * 1024
    total_written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(destination, "wb") as buffer:
            while True:
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"檔案大小超過單次上傳限制 (上限 {max_mb} MB)"
                    )
                buffer.write(chunk)
        return total_written
    except Exception:
        # 發生超標或任何寫入異常時，確保刪除殘留半成品檔案
        if destination.exists():
            try:
                destination.unlink()
            except OSError:
                pass
        raise
    finally:
        await upload_file.close()


def purge_expired_files(
    target_dirs: Iterable[Path],
    max_age_seconds: int = 86400,
    protected_names: Set[str] = frozenset({".gitkeep", "README.md", "user_template.docx", "template.docx"}),
    active_paths: Set[Path] = frozenset(),
) -> int:
    """
    24 小時無日誌檔案銷毀器：
    安全清除所有超過 max_age_seconds 的檔案與空資料夾，並避開保護名單與執行中任務。
    由下而上 (topdown=False) 遍歷，確保子檔案刪除後可順便清理過期空目錄。
    針對 Windows 檔案鎖定 (WinError 32) 進行異常隔離，不中斷整體巡檢。
    """
    now = time.time()
    deleted_count = 0
    resolved_active: Set[Path] = set()
    for p in active_paths:
        if p:
            try:
                resolved_active.add(Path(p).resolve())
            except Exception:
                pass

    for base_dir in target_dirs:
        if not base_dir or not base_dir.exists():
            continue
        for root, dirs, files in os.walk(base_dir, topdown=False):
            root_path = Path(root)
            for fname in files:
                if fname in protected_names:
                    continue
                fpath = root_path / fname
                try:
                    resolved_fpath = fpath.resolve()
                    if resolved_fpath in resolved_active:
                        continue
                    if (now - fpath.stat().st_mtime) > max_age_seconds:
                        fpath.unlink()
                        deleted_count += 1
                except OSError:
                    # Windows 檔案鎖定或權限異常時安全略過，不中斷整體清理
                    continue

            for dname in dirs:
                dpath = root_path / dname
                try:
                    # 若子資料夾已空且超過保存期限，則一併移除空目錄
                    if not any(dpath.iterdir()) and (now - dpath.stat().st_mtime) > max_age_seconds:
                        dpath.rmdir()
                        deleted_count += 1
                except OSError:
                    continue

    return deleted_count


def purge_in_memory_records(
    records_dict: dict,
    max_age_seconds: int = 86400,
    active_keys: Set[str] = frozenset(),
) -> int:
    """
    記憶體狀態清理器：
    清理已過期且非活躍的 in-memory 字典項目，杜絕伺服器長久運行下的記憶體洩漏。
    """
    now = time.time()
    keys_to_remove = []
    for k, v in list(records_dict.items()):
        if k in active_keys:
            continue
        if isinstance(v, dict):
            created_at = v.get("created_at")
            if created_at and (now - created_at) > max_age_seconds:
                keys_to_remove.append(k)

    for k in keys_to_remove:
        records_dict.pop(k, None)

    return len(keys_to_remove)
