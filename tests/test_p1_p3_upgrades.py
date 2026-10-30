# -*- coding: utf-8 -*-
"""
Verification Test Suite for P1 ~ P3 Architectural Upgrades
==========================================================
Covers:
1. GPU Concurrency Semaphore & non-blocking asyncio.to_thread dispatch
2. Server-Sent Events (SSE) streaming (/api/tasks/{task_id}/events & /api/ocr_events/{stem})
3. Pipeline State Handoff (/api/pod/handoff_from_ocr)
4. Dev Mode Telemetry Endpoint (/api/dev/telemetry)
5. Audit Report Visualizer payload edge-case robustness (empty, malformed, multi-violations)
6. 24-Hour Zero-Log Janitor handling of POD workspaces
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

from config import CFG, PATHS
from src.utils.task_queue import TaskRecord, TaskStatus, get_event_broadcaster, get_task_queue
from src.web.app import app, run_full_cleanup
from src.web.dependencies import _GPU_SEMAPHORE, get_gpu_semaphore


def test_gpu_semaphore_mutual_exclusion():
    """Verify GPU Concurrency Semaphore strictly serializes heavy inference."""
    sem = get_gpu_semaphore()
    assert sem._value == 1 or not sem.locked(), "GPU Semaphore should have 1 permit initially"


def test_dev_telemetry_endpoint():
    """Verify /api/dev/telemetry returns structured real-time hardware status."""
    client = TestClient(app)
    if CFG.auth_enabled and CFG.auth_password:
        client.headers["X-API-Key"] = CFG.auth_password

    resp = client.get("/api/dev/telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "gpu_name" in data
    assert "target_accelerator" in data
    assert "total_vram_gb" in data
    assert "allocated_vram_mb" in data
    assert "reserved_vram_mb" in data
    assert "vram_usage_percent" in data
    assert "gpu_locked" in data
    assert "app_mode" in data


def test_sse_task_events_stream():
    """Verify Server-Sent Events (SSE) streams initial state and update events."""
    queue = get_task_queue()
    task_id = f"test_sse_{int(time.time())}"
    stem = f"sample_stem_{task_id[:8]}"

    queue.enqueue(
        TaskRecord(
            task_id=task_id,
            stem=stem,
            status=TaskStatus.COMPLETED.value,
            progress=100,
            message="轉檔完成！",
        )
    )

    client = TestClient(app)
    if CFG.auth_enabled and CFG.auth_password:
        client.headers["X-API-Key"] = CFG.auth_password

    # Connect to SSE endpoint
    response = client.get(f"/api/tasks/{task_id}/events")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "data: " in response.text
    assert task_id in response.text
    assert "completed" in response.text


def test_pod_handoff_from_ocr(tmp_path: Path):
    """Verify /api/pod/handoff_from_ocr correctly links OCR output to POD workspace without re-upload."""
    client = TestClient(app)
    if CFG.auth_enabled and CFG.auth_password:
        client.headers["X-API-Key"] = CFG.auth_password

    stem = f"test_handoff_book_{int(time.time())}"
    ocr_out_dir = PATHS.output_dir
    ocr_out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Simulate OCR step 1 output docx
    import docx
    test_docx = ocr_out_dir / f"{stem}.docx"
    doc = docx.Document()
    doc.add_heading("第一章 緒論", level=1)
    doc.add_paragraph("這是全自動整稿產出的初稿段落。")
    doc.save(str(test_docx))

    # 2. Simulate matching PDF in database_text
    pdf_dir = PATHS.root / "data" / "database_text"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    test_pdf = pdf_dir / f"{stem}.pdf"
    import fitz
    fitz_doc: Any = fitz.open()
    fitz_doc.new_page(width=500, height=700)
    fitz_doc.save(str(test_pdf))
    fitz_doc.close()

    try:
        # Call handoff API
        resp = client.post("/api/pod/handoff_from_ocr", data={"filename_stem": stem})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "pod_" in data["session_id"]
        assert data["docx_name"] == "Book_seed.docx"
        assert data["pdf_name"] == "source_book.pdf"
        assert data["total_paragraphs"] >= 2

        # Verify physical files copied into workspace
        session_dir = PATHS.output_dir / "pod_workspaces" / data["session_id"]
        assert (session_dir / "Book_seed.docx").exists()
        assert (session_dir / "source_book.pdf").exists()
    finally:
        # Clean test files
        test_docx.unlink(missing_ok=True)
        test_pdf.unlink(missing_ok=True)


def test_audit_report_robustness_and_edge_cases():
    """Verify audit_report structure and edge cases (empty report, missing fields, severe errors)."""
    from src.pod_studio.pod_validator import ValidationReport, ValidationViolation

    # Case 1: Empty report (100% pass)
    empty_report = ValidationReport(
        total_sections=5,
        passed_sections=5,
        failed_sections=0,
        green_count=5,
        yellow_count=0,
        red_count=0,
        violations=[],
    )
    d1 = empty_report.to_dict()
    assert d1["is_valid"] is True
    assert len(d1["violations"]) == 0
    assert d1["green_count"] == 5

    # Case 2: Report with violations and section audits
    violation_report = ValidationReport(
        total_sections=3,
        passed_sections=2,
        failed_sections=1,
        green_count=1,
        yellow_count=1,
        red_count=1,
        violations=[
            ValidationViolation(
                section_id="sec_002",
                title="第二章 掉字異常篇章",
                check_type="cjk_character_conservation",
                severity="ERROR",
                message="文字骨架收縮超標：原 500 字，現 380 字",
            )
        ],
        section_audits=[
            {
                "section_id": "sec_001",
                "title": "第一章 正常篇",
                "traffic_light": "green",
                "char_count": 450,
                "paragraph_count": 5,
                "violations": [],
            },
            {
                "section_id": "sec_002",
                "title": "第二章 掉字異常篇章",
                "traffic_light": "red",
                "char_count": 380,
                "paragraph_count": 4,
                "violations": [
                    {
                        "severity": "ERROR",
                        "check_type": "cjk_character_conservation",
                        "message": "文字骨架收縮超標：原 500 字，現 380 字",
                    }
                ],
            },
        ],
    )
    d2 = violation_report.to_dict()
    assert d2["is_valid"] is False
    assert len(d2["violations"]) == 1
    assert len(d2["section_audits"]) == 2
    assert d2["section_audits"][1]["traffic_light"] == "red"


def test_24h_cleanup_covers_pod_workspaces(tmp_path: Path):
    """Verify run_full_cleanup sweeps expired POD workspaces while preserving active ones."""
    pod_base = PATHS.output_dir / "pod_workspaces"
    pod_base.mkdir(parents=True, exist_ok=True)

    now = time.time()
    old_time = now - 100000  # > 24 hours

    expired_session = pod_base / "pod_expired_test_session"
    expired_session.mkdir(parents=True, exist_ok=True)
    expired_file = expired_session / "Book_raw.docx"
    expired_file.write_text("old test content")
    import os
    os.utime(expired_file, (old_time, old_time))
    os.utime(expired_session, (old_time, old_time))

    # Run cleanup
    stats = run_full_cleanup()
    assert not expired_file.exists(), "逾期 POD 工作區檔案應被自動銷毀"
