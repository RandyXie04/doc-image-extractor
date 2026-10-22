# -*- coding: utf-8 -*-
"""
Unit Tests for P2 Enhancements:
1. Canonical founder_tools imports & exports
2. AI Kaiti classifier gate unlock and confidence thresholding
3. Persistent SQLite Task Queue with Celery adapter interface & crash recovery
4. Web API queue management and progress fallback endpoints
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.founder_tools import (
    clean_founder_text,
    HeadingDetector,
    MarkerDetector,
    AIKaitiClassifier,
)
from src.founder_tools.auto_footnote import AutoFootnoteEngine
from src.founder_tools.parsers.docx_parser import DocxParser
from src.founder_tools.parsers.pdf_parser import PdfParser
from src.utils.task_queue import (
    PersistentSQLiteTaskQueue,
    TaskRecord,
    TaskStatus,
    get_task_queue,
)
from config.settings import CFG


class TestCanonicalFounderTools(unittest.TestCase):
    """驗證 founder_tools 匯入標準化與公開符號解析"""

    def test_canonical_symbols_exported(self):
        self.assertTrue(callable(clean_founder_text))
        self.assertTrue(issubclass(HeadingDetector, object))
        self.assertTrue(issubclass(MarkerDetector, object))
        self.assertTrue(issubclass(AIKaitiClassifier, object))

    def test_parsers_and_engine_importable(self):
        self.assertTrue(issubclass(DocxParser, object))
        self.assertTrue(issubclass(PdfParser, object))
        self.assertTrue(issubclass(AutoFootnoteEngine, object))


class TestAIKaitiClassifierThreshold(unittest.TestCase):
    """驗證 AI 楷體閾值控管與信心度解鎖邏輯"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_file = os.path.join(self.temp_dir, "test_kaiti_cache.json")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_confidence_threshold_filtering(self):
        # 門檻設為 0.75
        classifier = AIKaitiClassifier(
            api_key="dummy_api_key_for_test",
            cache_dir=self.temp_dir,
            min_confidence=0.75,
        )

        dummy_page = MagicMock()
        dummy_bbox = [0, 0, 100, 50]

        with patch.object(classifier, "_render_block_screenshot", return_value=b"dummy_png_bytes"):
            # 1. 模擬 Gemini API 回傳低於 0.75 的信心度 (例如 0.60)
            with patch.object(classifier, "_call_gemini_vision", return_value={"font": "kaiti", "confidence": 0.60}):
                tag = classifier.classify_block_font(
                    dummy_page,
                    dummy_bbox,
                    block_text="低信心度測試文字",
                    font_names=["TestFontA"],
                )
                self.assertEqual(tag, "other", "低於 min_confidence 的字體不應被判定為 kaiti")
                self.assertNotIn("testfonta", classifier._font_name_cache)

            # 2. 模擬回傳滿足門檻的信心度 (例如 0.85)
            with patch.object(classifier, "_call_gemini_vision", return_value={"font": "kaiti", "confidence": 0.85}):
                tag = classifier.classify_block_font(
                    dummy_page,
                    dummy_bbox,
                    block_text="高信心度楷體測試文字",
                    font_names=["TestFontB"],
                )
                self.assertEqual(tag, "kaiti")
                self.assertEqual(classifier.lookup_font_name("TestFontB"), "kaiti")

    def test_global_config_has_ai_kaiti_threshold(self):
        self.assertTrue(hasattr(CFG, "ai_kaiti_threshold"))
        self.assertIsInstance(CFG.ai_kaiti_threshold, float)
        self.assertGreater(CFG.ai_kaiti_threshold, 0.0)
        self.assertLessEqual(CFG.ai_kaiti_threshold, 1.0)


class TestPersistentSQLiteTaskQueue(unittest.TestCase):
    """驗證 SQLite 持久化任務佇列之 CRUD、狀態轉換與異常中斷重啟恢復"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_queue.db")
        from pathlib import Path
        self.queue = PersistentSQLiteTaskQueue(db_path=Path(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_enqueue_and_retrieve_task(self):
        task = TaskRecord(
            task_id="task_test_001",
            stem="sample_doc",
            status=TaskStatus.QUEUED.value,
            progress=0,
            message="排隊中...",
            engine="auto",
            payload={"ai_kaiti": True, "ai_kaiti_threshold": 0.70},
        )
        self.queue.enqueue(task)

        # 依 task_id 查詢
        fetched = self.queue.get_task("task_test_001")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.stem, "sample_doc")
        self.assertEqual(fetched.status, TaskStatus.QUEUED.value)
        self.assertEqual(fetched.payload.get("ai_kaiti"), True)

        # 依 stem 查詢
        by_stem = self.queue.get_task_by_stem("sample_doc")
        self.assertIsNotNone(by_stem)
        self.assertEqual(by_stem.task_id, "task_test_001")

    def test_update_and_list_tasks(self):
        task = TaskRecord(
            task_id="task_test_002",
            stem="sample_doc_2",
            status=TaskStatus.QUEUED.value,
            progress=0,
        )
        self.queue.enqueue(task)

        # 更新進度與狀態
        self.queue.update_task(
            "task_test_002",
            status=TaskStatus.RUNNING.value,
            progress=50,
            message="正在辨識第 5 頁...",
        )
        updated = self.queue.get_task("task_test_002")
        self.assertEqual(updated.status, TaskStatus.RUNNING.value)
        self.assertEqual(updated.progress, 50)
        self.assertEqual(updated.message, "正在辨識第 5 頁...")

        # 依狀態過濾清單
        running_tasks = self.queue.list_tasks(status=TaskStatus.RUNNING.value)
        self.assertEqual(len(running_tasks), 1)
        self.assertEqual(running_tasks[0].task_id, "task_test_002")

    def test_cancel_task(self):
        task = TaskRecord(
            task_id="task_test_003",
            stem="sample_doc_3",
            status=TaskStatus.QUEUED.value,
        )
        self.queue.enqueue(task)
        cancelled = self.queue.cancel_task("task_test_003")
        self.assertTrue(cancelled)

        record = self.queue.get_task("task_test_003")
        self.assertEqual(record.status, TaskStatus.CANCELLED.value)

    def test_server_restart_auto_recovery(self):
        # 模擬伺服器崩潰前遺留的執行中任務
        task = TaskRecord(
            task_id="task_stale_004",
            stem="crash_doc",
            status=TaskStatus.RUNNING.value,
            progress=60,
            message="正在執行...",
        )
        self.queue.enqueue(task)

        # 觸發伺服器重啟復原
        recovered_count = self.queue.recover_interrupted_tasks()
        self.assertEqual(recovered_count, 1)

        rec = self.queue.get_task("task_stale_004")
        self.assertEqual(rec.status, TaskStatus.FAILED.value)
        self.assertIn("伺服器重啟", rec.message)


class TestWebAPIQueueEndpoints(unittest.TestCase):
    """驗證 Web API 佇列管理端點與進度查詢 fallback 機制"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from src.web.app import app
        from config.settings import CFG
        cls.client = TestClient(app)
        if CFG.auth_enabled and CFG.auth_password:
            cls.client.headers["X-API-Key"] = CFG.auth_password

    def test_queue_tasks_endpoint(self):
        resp = self.client.get("/api/queue/tasks")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tasks", data)
        self.assertIsInstance(data["tasks"], list)

    def test_ocr_progress_fallback_to_queue(self):
        # 向 task queue 插入一筆記錄，但不存入 ocr_progress_dict
        queue = get_task_queue()
        task = TaskRecord(
            task_id="test_fallback_task_99",
            stem="unique_stem_fallback_test",
            status=TaskStatus.COMPLETED.value,
            progress=100,
            message="轉檔完成！",
        )
        queue.enqueue(task)

        # 查詢 progress API，驗證在記憶體查無時自動從 DB 恢復
        resp = self.client.get("/api/ocr_progress/unique_stem_fallback_test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("progress"), 100)
        self.assertEqual(data.get("status"), TaskStatus.COMPLETED.value)
        self.assertEqual(data.get("task_id"), "test_fallback_task_99")


if __name__ == "__main__":
    unittest.main()
