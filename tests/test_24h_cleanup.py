# -*- coding: utf-8 -*-
import os
import time
from pathlib import Path

from src.utils.file_guard import purge_expired_files, purge_in_memory_records
from src.utils.task_queue import PersistentSQLiteTaskQueue, TaskRecord, TaskStatus
from src.web.app import run_full_cleanup


def test_purge_expired_files_and_protection(tmp_path: Path):
    """驗證檔案清理器：銷毀超過 24 小時之檔案與空目錄，但保護活躍中檔案與白名單"""
    test_dir = tmp_path / "test_lifecycle"
    test_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    old_time = now - 100000  # > 24 小時 (86400s)
    fresh_time = now - 3600  # 1 小時內

    # 1. 逾期的一般檔案 (應被刪除)
    expired_file = test_dir / "expired.pdf"
    expired_file.write_text("expired content")
    os.utime(expired_file, (old_time, old_time))

    # 2. 未逾期之新檔案 (應被保留)
    fresh_file = test_dir / "fresh.pdf"
    fresh_file.write_text("fresh content")
    os.utime(fresh_file, (fresh_time, fresh_time))

    # 3. 逾期但處於活躍白名單的檔案 (應被保留)
    active_file = test_dir / "active_processing.pdf"
    active_file.write_text("processing content")
    os.utime(active_file, (old_time, old_time))

    # 4. 逾期但屬於受保護名稱 (如範本、說明檔，應被保留)
    protected_file = test_dir / "README.md"
    protected_file.write_text("keep me")
    os.utime(protected_file, (old_time, old_time))

    # 5. 逾期的空子資料夾 (應被清理)
    empty_sub = test_dir / "empty_old_folder"
    empty_sub.mkdir()
    os.utime(empty_sub, (old_time, old_time))

    # 執行清理
    deleted_count = purge_expired_files(
        target_dirs=[test_dir],
        max_age_seconds=86400,
        protected_names={".gitkeep", "README.md", "user_template.docx"},
        active_paths={active_file}
    )

    assert not expired_file.exists(), "逾期檔案應被刪除"
    assert not empty_sub.exists(), "逾期之空目錄應被移除"
    assert fresh_file.exists(), "未逾期檔案必須保留"
    assert active_file.exists(), "任務處理中活躍檔案必須受保護保留"
    assert protected_file.exists(), "受保護之 README/範本檔必須保留"
    assert deleted_count >= 2


def test_purge_in_memory_records():
    """驗證 In-Memory 狀態字典淘汰機制，杜絕記憶體洩漏"""
    now = time.time()
    records = {
        "task_1_old": {"created_at": now - 100000, "status": "completed"},
        "task_2_fresh": {"created_at": now - 1000, "status": "completed"},
        "task_3_active_old": {"created_at": now - 100000, "status": "processing"}
    }

    deleted = purge_in_memory_records(
        records,
        max_age_seconds=86400,
        active_keys={"task_3_active_old"}
    )

    assert deleted == 1
    assert "task_1_old" not in records
    assert "task_2_fresh" in records
    assert "task_3_active_old" in records


def test_sqlite_task_queue_cleanup_and_active_paths(tmp_path: Path):
    """驗證 SQLite 任務資料庫超過 24 小時紀錄清理與活躍路徑提取"""
    db_file = tmp_path / "test_queue.db"
    queue = PersistentSQLiteTaskQueue(db_file)

    now = time.time()
    old_time = now - 100000
    active_pdf = tmp_path / "book_processing.pdf"

    # 加入四種類型任務
    queue.enqueue(TaskRecord(
        task_id="t1_done_old",
        stem="done_book",
        status=TaskStatus.COMPLETED.value,
        updated_at=old_time
    ))
    # 手動更新 updated_at 為過期時間
    with queue._get_connection() as conn:
        conn.execute("UPDATE task_records SET updated_at = ? WHERE task_id = 't1_done_old'", (old_time,))
        conn.commit()

    queue.enqueue(TaskRecord(
        task_id="t2_running",
        stem="running_book",
        status=TaskStatus.RUNNING.value,
        payload={"file_path": str(active_pdf)}
    ))

    queue.enqueue(TaskRecord(
        task_id="t3_fresh_done",
        stem="fresh_book",
        status=TaskStatus.COMPLETED.value,
        updated_at=now
    ))

    # 檢查提取活躍檔案路徑
    active_paths = queue.get_active_payload_paths()
    assert any(str(active_pdf) in str(p) for p in active_paths)

    # 執行過期任務銷毀
    purged = queue.cleanup_expired_tasks(max_age_seconds=86400)
    assert purged == 1

    # 驗證
    assert queue.get_task("t1_done_old") is None
    assert queue.get_task("t2_running") is not None
    assert queue.get_task("t3_fresh_done") is not None


def test_run_full_cleanup_smoke():
    """驗證全系統清理整合函式能平穩執行且回傳標準統計指標"""
    stats = run_full_cleanup()
    assert isinstance(stats, dict)
    assert "deleted_files" in stats
    assert "purged_db_tasks" in stats
    assert "purged_mem_records" in stats
