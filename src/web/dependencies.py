# -*- coding: utf-8 -*-
"""
Web Layer Shared Dependencies (Decoupled Dependency Injection)
==============================================================
Centralizes shared configuration, paths, concurrency semaphores,
and utility guards to prevent circular imports between FastAPI routers and app.py.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Set

from fastapi import Request

from config import PATHS, CFG, AI, VERSION
from src.utils.file_guard import save_upload_file_safely, purge_expired_files, purge_in_memory_records
from src.utils.task_queue import get_task_queue, BaseTaskQueue

__all__ = [
    # Configuration re-exports
    "PATHS",
    "CFG",
    "AI",
    "VERSION",
    # File guard re-exports
    "save_upload_file_safely",
    "purge_expired_files",
    "purge_in_memory_records",
    # Task queue re-exports
    "get_task_queue",
    "BaseTaskQueue",
    # Concurrency locks and helpers
    "_GPU_SEMAPHORE",
    "_OCR_SEMAPHORE",
    "_BACKGROUND_TASKS",
    "get_gpu_semaphore",
    "track_background_task",
    # Local dev request detection
    "get_local_dev_ips",
    "is_local_dev_request",
]

# Global Concurrency Locks
# Limits concurrent heavy AI / OCR / VLM operations to 1 on RTX 3060 (12GB VRAM)
# Prevents CUDA Out-Of-Memory while keeping web service responsive.
_GPU_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(1)

# Backward-compatibility alias for tests referencing _OCR_SEMAPHORE
_OCR_SEMAPHORE = _GPU_SEMAPHORE

# Global set for retaining asyncio background task references against Python GC
_BACKGROUND_TASKS: Set[asyncio.Task] = set()


def get_gpu_semaphore() -> asyncio.Semaphore:
    """Return the global GPU execution semaphore."""
    return _GPU_SEMAPHORE


def track_background_task(task: asyncio.Task) -> asyncio.Task:
    """Retain strong reference to asyncio task to prevent early GC collection."""
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


def get_local_dev_ips() -> set[str]:
    """取得開發本機所有 Loopback 與本機網卡 IP 位址集合"""
    ips = {"127.0.0.1", "::1", "localhost", "testclient"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            if addr:
                ips.add(str(addr).split("%")[0])
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except Exception:
        pass
    return ips


def is_local_dev_request(request: Request) -> bool:
    """偵測請求來源是否為開發本機 IP 位址"""
    client_host = (request.client.host if request.client else "").strip()
    if not client_host:
        return False
    normalized = client_host.split("%")[0]
    if normalized.startswith("::ffff:"):
        normalized = normalized[7:]
    return normalized in get_local_dev_ips()
