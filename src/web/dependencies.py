# -*- coding: utf-8 -*-
"""
Web Layer Shared Dependencies (Decoupled Dependency Injection)
==============================================================
Centralizes shared configuration, paths, concurrency semaphores,
and utility guards to prevent circular imports between FastAPI routers and app.py.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Set
from pathlib import Path

from config import PATHS, CFG, AI, VERSION
from src.utils.file_guard import save_upload_file_safely, purge_expired_files, purge_in_memory_records
from src.utils.task_queue import get_task_queue, BaseTaskQueue

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
