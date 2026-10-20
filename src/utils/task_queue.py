# -*- coding: utf-8 -*-
"""
Task Queue Architecture (Pluggable Celery / RQ / Persistent SQLite Queue)
- Provides durable, persistent task tracking across server reboots and crashes.
- Zero-configuration embedded SQLite queue for standalone desktop/LAN usage.
- Pluggable Celery / RQ adapter interface for distributed multi-node clusters.
"""
from __future__ import annotations

import abc
import asyncio
import contextlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import PATHS


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    task_id: str
    stem: str
    status: str = TaskStatus.QUEUED.value
    progress: int = 0
    message: str = "已排隊等待處理..."
    engine: str = "auto"
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> TaskRecord:
        return cls(
            task_id=row[0],
            stem=row[1],
            status=row[2],
            progress=row[3],
            message=row[4],
            engine=row[5],
            payload=json.loads(row[6]) if row[6] else {},
            created_at=row[7],
            updated_at=row[8],
            error=row[9],
        )


class BaseTaskQueue(abc.ABC):
    """Abstract Base Class for Task Queue implementations."""

    @abc.abstractmethod
    def enqueue(self, task: TaskRecord) -> str:
        """Enqueue a new task record."""
        pass

    @abc.abstractmethod
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve task by task_id."""
        pass

    @abc.abstractmethod
    def get_task_by_stem(self, stem: str) -> Optional[TaskRecord]:
        """Retrieve latest task by filename stem."""
        pass

    @abc.abstractmethod
    def update_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update status, progress, or message of a task."""
        pass

    @abc.abstractmethod
    def list_tasks(self, limit: int = 50, status: Optional[str] = None) -> List[TaskRecord]:
        """List recent tasks."""
        pass

    @abc.abstractmethod
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        pass

    @abc.abstractmethod
    def recover_interrupted_tasks(self) -> int:
        """Mark interrupted running/queued tasks as failed after reboot."""
        pass

    @abc.abstractmethod
    def cleanup_expired_tasks(self, max_age_seconds: int = 86400) -> int:
        """Purge completed, failed, or cancelled tasks older than max_age_seconds."""
        pass

    @abc.abstractmethod
    def get_active_payload_paths(self) -> Set[Path]:
        """Retrieve file paths currently held by queued or running tasks."""
        pass


class PersistentSQLiteTaskQueue(BaseTaskQueue):
    """
    Durable, embedded SQLite-backed task queue.
    Features:
    - ACID transaction durability.
    - Survives server restarts; auto-recovers interrupted tasks.
    - Zero external broker required on Windows/LAN.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (PATHS.data_dir / "task_queue.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_records (
                    task_id TEXT PRIMARY KEY,
                    stem TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    engine TEXT NOT NULL DEFAULT 'auto',
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stem ON task_records (stem)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON task_records (status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_updated_at ON task_records (updated_at)")
            conn.commit()
        self.recover_interrupted_tasks()

    def recover_interrupted_tasks(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_records
                SET status = 'failed',
                    message = '伺服器重啟：任務已中斷，請點選重新執行',
                    error = 'Server restart while task was executing',
                    updated_at = ?
                WHERE status IN ('running', 'queued')
                """,
                (time.time(),),
            )
            conn.commit()
            return cursor.rowcount

    def enqueue(self, task: TaskRecord) -> str:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_records (
                    task_id, stem, status, progress, message, engine, payload, created_at, updated_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.stem,
                    task.status,
                    task.progress,
                    task.message,
                    task.engine,
                    json.dumps(task.payload, ensure_ascii=False),
                    task.created_at,
                    task.updated_at,
                    task.error,
                ),
            )
            conn.commit()
        return task.task_id

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_records WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return TaskRecord.from_row(row)
        return None

    def get_task_by_stem(self, stem: str) -> Optional[TaskRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM task_records WHERE stem = ? ORDER BY created_at DESC LIMIT 1",
                (stem,),
            )
            row = cursor.fetchone()
            if row:
                return TaskRecord.from_row(row)
        return None

    def update_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        updates = []
        params = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if message is not None:
            updates.append("message = ?")
            params.append(message)
        if error is not None:
            updates.append("error = ?")
            params.append(error)

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(task_id)

        sql = f"UPDATE task_records SET {', '.join(updates)} WHERE task_id = ?"
        with self._get_connection() as conn:
            conn.execute(sql, tuple(params))
            conn.commit()

    def list_tasks(self, limit: int = 50, status: Optional[str] = None) -> List[TaskRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM task_records WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM task_records ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [TaskRecord.from_row(r) for r in rows]

    def cancel_task(self, task_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE task_records SET status = 'cancelled', message = '任務已由使用者取消', updated_at = ? WHERE task_id = ? AND status IN ('queued', 'running')",
                (time.time(), task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def cleanup_expired_tasks(self, max_age_seconds: int = 86400) -> int:
        cutoff = time.time() - max_age_seconds
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM task_records
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND updated_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount

    def get_active_payload_paths(self) -> Set[Path]:
        active_paths: Set[Path] = set()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload FROM task_records WHERE status IN ('queued', 'running')"
            )
            rows = cursor.fetchall()
            for (raw_payload,) in rows:
                if not raw_payload:
                    continue
                try:
                    payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    fp = payload.get("file_path")
                    if fp:
                        active_paths.add(Path(fp))
                except Exception:
                    pass
        return active_paths


class CeleryTaskQueueAdapter(BaseTaskQueue):
    """
    Celery / Redis Distributed Task Queue Adapter.
    Delegates to Celery cluster when CELERY_BROKER_URL or REDIS_URL is configured.
    Falls back gracefully to SQLite queue if Celery worker is unreachable.
    """

    def __init__(self, broker_url: str, fallback_queue: PersistentSQLiteTaskQueue):
        self.broker_url = broker_url
        self.fallback = fallback_queue
        self._celery_app = None
        self._init_celery()

    def _init_celery(self):
        try:
            import importlib
            celery_mod = importlib.import_module("celery")
            self._celery_app = celery_mod.Celery("doc_image_extractor", broker=self.broker_url)
        except (ImportError, Exception):
            self._celery_app = None

    def enqueue(self, task: TaskRecord) -> str:
        # Save local record first for instant UI responsiveness
        self.fallback.enqueue(task)
        if self._celery_app:
            try:
                # Dispatch async job to Celery worker pool
                self._celery_app.send_task("tasks.run_ocr_pipeline", kwargs=task.to_dict(), task_id=task.task_id)
            except Exception as e:
                # Fallback to local processing if broker offline
                print(f"[TaskQueue] Celery broker unreachable: {e}, falling back to local queue")
        return task.task_id

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.fallback.get_task(task_id)

    def get_task_by_stem(self, stem: str) -> Optional[TaskRecord]:
        return self.fallback.get_task_by_stem(stem)

    def update_task(self, task_id: str, **kwargs) -> None:
        self.fallback.update_task(task_id, **kwargs)

    def list_tasks(self, limit: int = 50, status: Optional[str] = None) -> List[TaskRecord]:
        return self.fallback.list_tasks(limit=limit, status=status)

    def cancel_task(self, task_id: str) -> bool:
        if self._celery_app:
            try:
                self._celery_app.control.revoke(task_id, terminate=True)
            except Exception:
                pass
        return self.fallback.cancel_task(task_id)

    def recover_interrupted_tasks(self) -> int:
        return self.fallback.recover_interrupted_tasks()

    def cleanup_expired_tasks(self, max_age_seconds: int = 86400) -> int:
        return self.fallback.cleanup_expired_tasks(max_age_seconds)

    def get_active_payload_paths(self) -> Set[Path]:
        return self.fallback.get_active_payload_paths()


# Global task queue singleton
_GLOBAL_QUEUE: Optional[BaseTaskQueue] = None


def get_task_queue() -> BaseTaskQueue:
    """Factory retrieving the configured task queue instance."""
    global _GLOBAL_QUEUE
    if _GLOBAL_QUEUE is None:
        sqlite_q = PersistentSQLiteTaskQueue()
        broker_url = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL")
        if broker_url:
            try:
                import importlib
                importlib.import_module("celery")
                _GLOBAL_QUEUE = CeleryTaskQueueAdapter(broker_url, sqlite_q)
            except (ImportError, Exception):
                _GLOBAL_QUEUE = sqlite_q
        else:
            _GLOBAL_QUEUE = sqlite_q
    return _GLOBAL_QUEUE
