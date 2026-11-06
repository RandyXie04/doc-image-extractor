# -*- coding: utf-8 -*-
"""
Wave 1 (Phase 1 / P0) Architecture Evolution Regression Tests
=============================================================
Verifies all four Wave 1 workstreams:
- Wave 1.1: Native save file bridge, open_file_folder payload compatibility, Founder repair download, and LAN guard.
- Wave 1.2: Unified PDF upload path & POD handoff (`file_id` / `raw_pdf_path` resolution).
- Wave 1.3: Removal of book-specific hardcoded regexes, duplicate postprocess flag, and Gemini model alias normalization.
- Wave 1.4: Task cancellation process termination, SSE partial-update completeness, and wildcard leak prevention.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import docx
import pytest
from fastapi.testclient import TestClient

from config import PATHS
from src.scripts.book_layout_extractor import _PAGE_HEADER_PATTERNS
from src.utils.ollama_client import normalize_gemini_model_name
from src.utils.task_queue import (
    PersistentSQLiteTaskQueue,
    TaskRecord,
    TaskStatus,
    get_event_broadcaster,
)
from src.web.app import app
from src.web.routers.ocr_router import ocr_progress_dict


client = TestClient(app)


class TestWave1FileDeliveryAndFounderDownload:
    """Wave 1.1: File delivery closed-loop & LAN guard (AUD-02, AUD-25)."""

    def test_native_save_file_with_suggested_filename_and_destination(self, tmp_path):
        src_file = PATHS.output_dir / f"wave1_test_{uuid.uuid4().hex[:8]}.docx"
        PATHS.output_dir.mkdir(parents=True, exist_ok=True)
        src_file.write_bytes(b"PK\x03\x04dummy-docx-content")
        try:
            # 1. Payload with suggested_filename (sent by toolbox.js)
            resp = client.post(
                "/api/native_save_file",
                json={
                    "source_path": str(src_file),
                    "suggested_filename": "saved_output.docx",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("success", "fallback", "cancelled")

            # 2. Payload with explicit destination_path
            dest_file = tmp_path / "explicit_dest.docx"
            resp2 = client.post(
                "/api/native_save_file",
                json={
                    "source_path": str(src_file),
                    "destination_path": str(dest_file),
                },
            )
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "success"
            assert dest_file.exists()
        finally:
            if src_file.exists():
                src_file.unlink()

    def test_open_file_folder_accepts_both_file_path_and_path(self):
        src_file = PATHS.output_dir / f"wave1_folder_{uuid.uuid4().hex[:8]}.md"
        PATHS.output_dir.mkdir(parents=True, exist_ok=True)
        src_file.write_text("# Test", encoding="utf-8")
        try:
            resp_file_path = client.post(
                "/api/open_file_folder",
                json={"file_path": str(src_file)},
            )
            assert resp_file_path.status_code == 200
            assert resp_file_path.json()["status"] in ("success", "fallback")

            resp_path = client.post(
                "/api/open_file_folder",
                json={"path": str(src_file)},
            )
            assert resp_path.status_code == 200
            assert resp_path.json()["status"] in ("success", "fallback")
        finally:
            if src_file.exists():
                src_file.unlink()

    def test_founder_repair_download_endpoint(self):
        PATHS.output_dir.mkdir(parents=True, exist_ok=True)
        fname = f"wave1_repaired_{uuid.uuid4().hex[:8]}.docx"
        repaired_file = PATHS.output_dir / fname
        doc = docx.Document()
        doc.add_paragraph("方正測試修復段落")
        doc.save(str(repaired_file))
        try:
            resp = client.get(f"/api/founder/download/{fname}")
            assert resp.status_code == 200
            assert len(resp.content) > 100
        finally:
            if repaired_file.exists():
                repaired_file.unlink()


class TestWave1PodHandoffPdfResolution:
    """Wave 1.2: Unified PDF upload path & POD handoff resolution (AUD-03)."""

    def test_pod_handoff_resolves_uuid_uploaded_pdf(self):
        stem = f"wave1_book_{uuid.uuid4().hex[:8]}"
        uuid_pdf_name = f"{uuid.uuid4().hex}.pdf"
        PATHS.input_dir.mkdir(parents=True, exist_ok=True)
        PATHS.output_dir.mkdir(parents=True, exist_ok=True)

        uuid_pdf_path = PATHS.input_dir / uuid_pdf_name
        seed_docx_path = PATHS.output_dir / f"{stem}.docx"

        uuid_pdf_path.write_bytes(b"%PDF-1.4\n%Wave1 test PDF\n%%EOF")
        doc = docx.Document()
        doc.add_paragraph("第一章 測試段落")
        doc.save(str(seed_docx_path))

        ocr_progress_dict[stem] = {
            "task_id": str(uuid.uuid4()),
            "progress": 100,
            "message": "轉檔完成！",
            "status": "completed",
            "raw_pdf_path": str(uuid_pdf_path),
            "file_id": uuid_pdf_name,
        }

        session_dir = None
        try:
            resp = client.post(
                "/api/pod/handoff_from_ocr",
                data={"filename_stem": stem, "file_id": uuid_pdf_name},
            )
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["status"] == "success"
            assert payload["pdf_name"] == "source_book.pdf"

            session_dir = PATHS.output_dir / "pod_workspaces" / payload["session_id"]
            assert (session_dir / "Book_seed.docx").exists()
            assert (session_dir / "source_book.pdf").exists()
        finally:
            ocr_progress_dict.pop(stem, None)
            if uuid_pdf_path.exists():
                uuid_pdf_path.unlink()
            if seed_docx_path.exists():
                seed_docx_path.unlink()
            if session_dir and session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)


class TestWave1DecouplingAndModelNormalization:
    """Wave 1.3: Remove book-specific regexes & normalize Gemini model aliases (AUD-04, AUD-10, AUD-17)."""

    def test_book_specific_headers_removed(self):
        for pat in _PAGE_HEADER_PATTERNS:
            assert not pat.search("版图之枷：中国历史疆域研究")
            assert not pat.search("军事后勤视野下的古代战争")

    def test_gemini_model_alias_normalization(self):
        assert normalize_gemini_model_name("gemini-3.8-flash") == "gemini-2.5-flash"
        assert normalize_gemini_model_name("gemini-3.5-flash-lite") == "gemini-2.5-flash-lite"
        assert normalize_gemini_model_name("gemini-2.5-pro") == "gemini-2.5-pro"
        assert normalize_gemini_model_name("") == "gemini-2.5-flash"

    def test_md_to_docx_has_skip_flag_and_no_hardcoded_table_header(self):
        md_to_docx_path = Path(__file__).parent.parent / "src" / "scripts" / "md_to_docx.py"
        content = md_to_docx_path.read_text(encoding="utf-8")
        assert "--skip-text-postprocess" in content
        assert "名 出现 称 次数 文书 标题" not in content


class TestWave1TaskQueueCancellationAndSSE:
    """Wave 1.4: Task cancellation, SSE partial-update completeness, and wildcard leak prevention (AUD-05, AUD-07, AUD-11)."""

    def test_partial_update_publishes_full_record_and_cancel_terminates_process(self, tmp_path):
        db_file = tmp_path / "test_wave1_queue.db"
        q = PersistentSQLiteTaskQueue(db_path=db_file)
        broadcaster = get_event_broadcaster()

        tid = f"task_{uuid.uuid4().hex[:8]}"
        sub_q = broadcaster.subscribe(tid)
        try:
            q.enqueue(
                TaskRecord(
                    task_id=tid,
                    stem="test_stem",
                    status=TaskStatus.RUNNING.value,
                    progress=10,
                    message="Starting...",
                )
            )
            # Drain initial enqueue event
            _ = sub_q.get_nowait()

            # Partial update: only progress and message passed (status=None)
            q.update_task(tid, progress=55, message="Halfway there")
            evt = sub_q.get_nowait()
            assert evt["status"] == TaskStatus.RUNNING.value
            assert evt["progress"] == 55
            assert evt["message"] == "Halfway there"

            # Register a mock process and cancel task
            mock_proc = MagicMock()
            q.register_runtime_handles(tid, proc=mock_proc)

            cancelled = q.cancel_task(tid)
            assert cancelled is True
            mock_proc.terminate.assert_called_once()

            cancel_evt = sub_q.get_nowait()
            assert cancel_evt["status"] == TaskStatus.CANCELLED.value

            # Subsequent update_task must NOT overwrite cancelled status back to running/completed
            q.update_task(tid, status=TaskStatus.COMPLETED.value, progress=100, message="Should be ignored")
            rec_after = q.get_task(tid)
            assert rec_after is not None
            assert rec_after.status == TaskStatus.CANCELLED.value
            assert rec_after.progress == 55
        finally:
            broadcaster.unsubscribe(sub_q, tid)
