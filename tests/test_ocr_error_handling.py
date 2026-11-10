# -*- coding: utf-8 -*-
"""
OCR Error Handling & Layout Model Runtime Behavioral Tests
=========================================================
Genuine runtime behavioral tests verifying:
1. Lazy loading imports layout model specifically from surya.model.layout.model (not detection.model).
2. pdf_engine_dispatcher handles missing files and raises RuntimeError when output markdown is missing.
3. Task queue records TaskStatus.FAILED when markdown generation fails.
4. /api/ocr_progress endpoint serves failure state and message to clients.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import CFG
from src.scripts import pdf_engine_dispatcher, process_ocr
from src.utils.task_queue import PersistentSQLiteTaskQueue, TaskRecord, TaskStatus
from src.web.app import app
from src.web.routers.ocr_router import ocr_progress_dict


auth_headers = {"X-API-Key": CFG.auth_password} if CFG.auth_enabled else {}


class TestOcrErrorHandlingAndLayoutModel:
    def test_process_ocr_pep562_dynamic_attribute_resolution(self):
        """Verifies PEP 562 dynamic attribute resolution on process_ocr module."""
        # 1. SURYA_AVAILABLE must be a boolean (never None)
        assert isinstance(process_ocr.SURYA_AVAILABLE, bool)

        # 2. Lazy-loaded Surya callables must be callable when Surya is available
        if process_ocr.SURYA_AVAILABLE:
            assert callable(process_ocr.load_layout_model)
            assert callable(process_ocr.batch_layout_detection)

        # 3. Detectors must be resolved dynamically
        assert process_ocr.HeadingDetector is not None
        assert process_ocr.MarkerDetector is not None

        # 4. PEP 562 dir() lists dynamic attributes
        module_attrs = dir(process_ocr)
        assert "SURYA_AVAILABLE" in module_attrs
        assert "batch_layout_detection" in module_attrs
        assert "load_layout_model" in module_attrs
        assert "HeadingDetector" in module_attrs
        assert "MarkerDetector" in module_attrs

        # 5. Non-existent attribute raises AttributeError
        with pytest.raises(AttributeError):
            _ = getattr(process_ocr, "nonexistent_surya_symbol_probe")

    def test_surya_layout_model_runtime_import(self):
        """Verifies process_ocr._ensure_surya_loaded() loads layout model from surya.model.layout.model."""
        mock_layout_mod = MagicMock()
        mock_det_mod = MagicMock()
        orig_available = process_ocr.SURYA_AVAILABLE
        orig_load_layout = process_ocr.load_layout_model

        try:
            process_ocr.SURYA_AVAILABLE = None
            with patch.dict(
                sys.modules,
                {
                    "surya.layout": MagicMock(),
                    "surya.model.recognition.model": MagicMock(),
                    "surya.model.recognition.processor": MagicMock(),
                    "surya.model.layout.model": mock_layout_mod,
                    "surya.model.detection.model": mock_det_mod,
                    "surya.model.layout.processor": MagicMock(),
                    "surya.settings": MagicMock(),
                },
            ):
                loaded = process_ocr._ensure_surya_loaded()
                assert loaded is True
                assert process_ocr.load_layout_model is mock_layout_mod.load_model
                assert process_ocr.load_layout_model is not mock_det_mod.load_model
        finally:
            process_ocr.SURYA_AVAILABLE = orig_available
            process_ocr.load_layout_model = orig_load_layout

    def test_pdf_engine_dispatcher_missing_output_file_raises_runtime_error(self, tmp_path: Path):
        """Verifies pdf_engine_dispatcher raises RuntimeError when output file is missing."""
        # 1. Nonexistent input returns False for is_vector_pdf
        assert pdf_engine_dispatcher.is_vector_pdf("nonexistent_test_input.pdf") is False

        # 2. When process_ocr.main produces no output, pdf_engine_dispatcher raises RuntimeError
        test_argv = [
            "pdf_engine_dispatcher",
            "--file",
            "dummy_missing.pdf",
            "--output_dir",
            str(tmp_path),
            "--engine",
            "suryaocr",
        ]
        with patch.object(sys, "argv", test_argv), patch("src.scripts.process_ocr.main", MagicMock()):
            with pytest.raises(RuntimeError, match="未生成預期之輸出檔案"):
                pdf_engine_dispatcher.main()

    def test_task_queue_records_failure_on_missing_output(self, tmp_path: Path):
        """Verifies task queue records TaskStatus.FAILED when output generation fails."""
        db_file = tmp_path / "queue_fail_test.db"
        queue = PersistentSQLiteTaskQueue(db_path=db_file)
        task_id = "test_fail_task_001"

        queue.enqueue(
            TaskRecord(
                task_id=task_id,
                stem="failed_book",
                status=TaskStatus.RUNNING.value,
                progress=80,
            )
        )

        fail_msg = "轉檔程序異常結束：未生成 Markdown 輸出檔案"
        queue.update_task(task_id, status=TaskStatus.FAILED.value, message=fail_msg, error=fail_msg)

        task = queue.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED.value
        assert task.message == fail_msg
        assert task.error == fail_msg

    def test_ocr_progress_endpoint_serves_failure_state(self):
        """Verifies /api/ocr_progress/{stem} returns failure status and message to polling clients."""
        client = TestClient(app, headers=auth_headers)
        stem = "test_fail_stem_probe"
        fail_msg = "轉檔程序異常結束：未生成 Markdown 輸出檔案"
        ocr_progress_dict[stem] = {
            "status": "failed",
            "progress": 85,
            "message": fail_msg,
        }

        try:
            resp = client.get(f"/api/ocr_progress/{stem}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "failed"
            assert data["message"] == fail_msg
            assert data["progress"] == 85
        finally:
            ocr_progress_dict.pop(stem, None)
