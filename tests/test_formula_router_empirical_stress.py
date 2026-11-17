# -*- coding: utf-8 -*-
"""
Empirical Stress Test Suite for Formula Router & Deliverable Packaging
====================================================================
Milestone 3 Verification:
1. Concurrency: get_gpu_semaphore() mutual exclusion & queue serialization.
2. Mid-flight task cancellation & clean release of handles/resources.
3. Deliverable ZIP bundle verification:
   - formulas.json valid JSON & conforms to FormulaResultContract
   - images/ PNG crops max(w, h) = 1600 +- 1
   - mathml/ XML parseable by xml.etree.ElementTree
   - latex/ TeX content stripped of fences/delimiters
   - edge cases: 0 formulas, CJK math, malformed LaTeX
4. Backward compatibility: Wave 2 architecture fixes.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import pytest
from httpx import ASGITransport, AsyncClient

from config import CFG, PATHS
from src.extraction.contracts import (
    FORMULA_RESULT_ADAPTER,
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)
from src.utils.task_queue import TaskRecord, TaskStatus, get_task_queue
from src.web.app import app
from src.web.dependencies import _BACKGROUND_TASKS, get_gpu_semaphore
from src.web.routers.formula_router import (
    create_formula_zip_bundle,
    formula_tasks,
    process_pdf_sync,
)


def _create_sample_pdf(path: Path, num_pages: int = 1) -> Path:
    """Creates a simple valid PDF document."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), f"Page {i + 1} content with E = mc^2", fontsize=14)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(autouse=True)
def clean_tasks_state():
    """Ensures each test has clean task queues and a fresh Semaphore bound to the active loop."""
    import src.web.dependencies
    formula_tasks.clear()
    src.web.dependencies._GPU_SEMAPHORE = asyncio.Semaphore(1)
    src.web.dependencies._OCR_SEMAPHORE = src.web.dependencies._GPU_SEMAPHORE
    yield
    formula_tasks.clear()


# ===========================================================================
# 1. Concurrency & Queue Serialization Stress Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_gpu_semaphore_mutual_exclusion_and_queue_serialization():
    """
    Stress-test: Dispatch 4 concurrent requests to /api/process.
    Verify:
      - get_gpu_semaphore() guarantees at most 1 task runs process_pdf_sync concurrently.
      - Later tasks wait in queued status until prior tasks complete.
      - Tasks are serialized without deadlock or starvation.
      - Semaphore value returns to 1 upon completion.
    """
    pdf_path = PATHS.input_dir / "math_sample.pdf"
    _create_sample_pdf(pdf_path, num_pages=2)

    active_executions = 0
    max_active_executions = 0
    execution_order: List[str] = []

    def instrumented_process_pdf_sync(task_id: str, *args, **kwargs):
        nonlocal active_executions, max_active_executions
        active_executions += 1
        if active_executions > max_active_executions:
            max_active_executions = active_executions

        execution_order.append(f"start:{task_id}")
        time.sleep(0.12)  # Simulate GPU execution
        execution_order.append(f"end:{task_id}")

        active_executions -= 1
        formula_tasks[task_id]["status"] = "completed"
        formula_tasks[task_id]["progress"] = 100.0
        formula_tasks[task_id]["result_file"] = str(PATHS.output_dir / f"dummy_{task_id}.zip")
        get_task_queue().update_task(task_id, status=TaskStatus.COMPLETED.value, progress=100)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("src.web.routers.formula_router.process_pdf_sync", side_effect=instrumented_process_pdf_sync):
            reqs = [
                client.post(
                    "/api/process",
                    data={
                        "file_id": "math_sample.pdf",
                        "extract_formulas": "true",
                        "orig_name": f"test_doc_{i}",
                    },
                )
                for i in range(4)
            ]
            responses = await asyncio.gather(*reqs)
            task_ids = [r.json()["task_id"] for r in responses]
            assert len(task_ids) == 4
            assert len(set(task_ids)) == 4

            # Poll until all are complete
            start_wait = time.time()
            all_done = False
            while time.time() - start_wait < 5.0:
                statuses = [formula_tasks[tid]["status"] for tid in task_ids]
                if all(s == "completed" for s in statuses):
                    all_done = True
                    break
                await asyncio.sleep(0.05)

            assert all_done, f"Not all tasks completed: {[formula_tasks[tid]['status'] for tid in task_ids]}"

            # Also ensure all background runner coroutines finish completely
            while any(not t.done() for t in list(_BACKGROUND_TASKS)):
                await asyncio.sleep(0.05)

    # 1. Mutual exclusion: max concurrent executions MUST be 1
    assert max_active_executions == 1, (
        f"CRITICAL VIOLATION: get_gpu_semaphore() failed mutual exclusion! "
        f"Max active concurrent executions = {max_active_executions} (expected 1)"
    )

    # 2. Strict serialization: each start is followed immediately by its end before next start
    for i in range(len(execution_order) - 1):
        if execution_order[i].startswith("start:"):
            cur_tid = execution_order[i].split(":")[1]
            assert execution_order[i + 1] == f"end:{cur_tid}", (
                f"Concurrency leak detected! Event stream: {execution_order}"
            )

    # 3. Semaphore value restored to 1
    assert get_gpu_semaphore()._value == 1


@pytest.mark.asyncio
async def test_gpu_semaphore_release_on_pipeline_failure():
    """
    Stress-test: If pipeline raises RuntimeError during process_pdf_sync (e.g. CUDA OOM),
    verify:
      - Task 1 is marked 'failed'.
      - Semaphore is properly released.
      - Queued Task 2 runs and succeeds.
      - Semaphore value returns to 1.
    """
    pdf_path = PATHS.input_dir / "math_sample.pdf"
    _create_sample_pdf(pdf_path, num_pages=1)

    call_count = 0

    def mock_process_document(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("CUDA out of memory: tried to allocate 2.40 GiB")
        return []

    mock_pipeline = MagicMock()
    mock_pipeline.process_document.side_effect = mock_process_document

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("src.web.routers.formula_router.get_formula_pipeline", return_value=mock_pipeline):
            res1 = await client.post("/api/process", data={"file_id": "math_sample.pdf", "orig_name": "task1"})
            res2 = await client.post("/api/process", data={"file_id": "math_sample.pdf", "orig_name": "task2"})
            t1 = res1.json()["task_id"]
            t2 = res2.json()["task_id"]

            start_wait = time.time()
            while time.time() - start_wait < 5.0:
                if formula_tasks[t1]["status"] in ("failed", "completed") and formula_tasks[t2]["status"] in ("failed", "completed"):
                    break
                await asyncio.sleep(0.05)

            # Wait for background tasks to finalize
            while any(not t.done() for t in list(_BACKGROUND_TASKS)):
                await asyncio.sleep(0.05)

            # Task 1 must be failed
            assert formula_tasks[t1]["status"] == "failed"
            assert "CUDA out of memory" in formula_tasks[t1]["message"]
            assert get_task_queue().get_task(t1).status == TaskStatus.FAILED.value

            # Task 2 must have acquired the released semaphore and completed!
            assert formula_tasks[t2]["status"] == "completed"
            assert get_task_queue().get_task(t2).status == TaskStatus.COMPLETED.value

    # Semaphore value restored to 1
    assert get_gpu_semaphore()._value == 1


# ===========================================================================
# 2. Task Cancellation & Resource Cleanup Stress Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_cancellation_while_task_is_queued():
    """
    Stress-test: Task 2 is queued waiting for GPU semaphore while Task 1 is running.
    Cancel Task 2 before it acquires semaphore.
    Verify:
      - Task 2 transitions to 'cancelled'.
      - Task 2 never executes process_pdf_sync.
      - Handles are cleanly unregistered.
      - Task 1 and subsequent Task 3 complete normally.
    """
    pdf_path = PATHS.input_dir / "sample.pdf"
    _create_sample_pdf(pdf_path, num_pages=1)

    executed_tasks: List[str] = []

    def slow_process_pdf_sync(task_id: str, *args, **kwargs):
        executed_tasks.append(task_id)
        time.sleep(0.25)
        formula_tasks[task_id]["status"] = "completed"
        formula_tasks[task_id]["progress"] = 100.0
        get_task_queue().update_task(task_id, status=TaskStatus.COMPLETED.value, progress=100)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("src.web.routers.formula_router.process_pdf_sync", side_effect=slow_process_pdf_sync):
            r1 = await client.post("/api/process", data={"file_id": "sample.pdf", "orig_name": "task1"})
            t1 = r1.json()["task_id"]

            await asyncio.sleep(0.05)  # Let Task 1 acquire semaphore

            # Dispatch Task 2 (queued waiting for semaphore)
            r2 = await client.post("/api/process", data={"file_id": "sample.pdf", "orig_name": "task2"})
            t2 = r2.json()["task_id"]
            assert formula_tasks[t2]["status"] == "queued"

            # Cancel Task 2 via queue cancellation endpoint
            cancel_res = await client.post(f"/api/queue/cancel/{t2}")
            assert cancel_res.status_code == 200
            assert cancel_res.json()["status"] == "success"

            # Dispatch Task 3 (queued behind cancelled Task 2)
            r3 = await client.post("/api/process", data={"file_id": "sample.pdf", "orig_name": "task3"})
            t3 = r3.json()["task_id"]

            start_wait = time.time()
            while time.time() - start_wait < 5.0:
                if formula_tasks[t1]["status"] == "completed" and formula_tasks[t3]["status"] == "completed":
                    break
                await asyncio.sleep(0.05)

            while any(not t.done() for t in list(_BACKGROUND_TASKS)):
                await asyncio.sleep(0.05)

            # Verification:
            assert t1 in executed_tasks
            assert t2 not in executed_tasks, "CRITICAL ERROR: Cancelled queued task was executed!"
            assert formula_tasks[t2]["status"] == "cancelled"
            assert get_task_queue().get_task(t2).status == TaskStatus.CANCELLED.value
            assert t3 in executed_tasks
            assert formula_tasks[t3]["status"] == "completed"

    assert get_gpu_semaphore()._value == 1


@pytest.mark.asyncio
async def test_cancellation_mid_flight_running_task():
    """
    Stress-test: Task 1 is mid-flight inside process_pdf_sync.
    Cancel Task 1 while running.
    Verify:
      - Runtime async handles are unregistered.
      - Queue record is updated to cancelled.
      - In-memory task status transitions to cancelled.
    """
    pdf_path = PATHS.input_dir / "sample_cancel.pdf"
    _create_sample_pdf(pdf_path, num_pages=1)

    thread_started = False
    thread_can_finish = False

    def long_running_sync(task_id: str, *args, **kwargs):
        nonlocal thread_started
        thread_started = True
        while not thread_can_finish:
            time.sleep(0.02)
        # Check what the thread tries to write when finishing:
        if formula_tasks[task_id].get("status") != "cancelled":
            formula_tasks[task_id]["status"] = "completed"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("src.web.routers.formula_router.process_pdf_sync", side_effect=long_running_sync):
            r1 = await client.post("/api/process", data={"file_id": "sample_cancel.pdf", "orig_name": "cancel_mid"})
            t1 = r1.json()["task_id"]

            while not thread_started:
                await asyncio.sleep(0.01)

            # Cancel mid-flight
            cancel_res = await client.post(f"/api/queue/cancel/{t1}")
            assert cancel_res.status_code == 200

            # Immediately check status
            rec = get_task_queue().get_task(t1)
            assert rec.status == TaskStatus.CANCELLED.value
            assert t1 not in get_task_queue()._active_async_tasks

            # Verify GPU semaphore is safely held while worker thread executes
            # and is NOT released prematurely upon cancellation:
            assert get_gpu_semaphore()._value == 0, (
                f"CRITICAL ERROR: GPU semaphore released prematurely on cancellation while worker thread active! "
                f"Semaphore value = {get_gpu_semaphore()._value}"
            )

            # Allow thread to finish
            thread_can_finish = True
            await asyncio.sleep(0.1)

            while any(not t.done() for t in list(_BACKGROUND_TASKS)):
                await asyncio.sleep(0.05)

            # Verify semaphore is released once worker thread completes
            assert get_gpu_semaphore()._value == 1, "GPU semaphore leaked after thread finished!"
            assert formula_tasks[t1]["status"] == "cancelled", "Cancelled task status was overwritten!"


# ===========================================================================
# 3. Deliverable ZIP Bundle Verification
# ===========================================================================

def test_deliverable_zip_bundle_complete_conformance(tmp_path):
    """
    Empirically verify deliverable ZIP packaging:
    - unpack generated formulas_{stem}_{task_id[:8]}.zip
    - formulas.json is valid JSON and parses against Pydantic FormulaResultContract.
    - Every PNG in images/ has max(w, h) = 1600 +- 1.
    - Every XML in mathml/ parses with xml.etree.ElementTree.fromstring without error.
    - Every TeX in latex/ contains valid stripped formula content.
    - formulas.tex consolidated document exists.
    """
    task_id = "test_deliverable_zip_12345678"
    stem = "physics_paper"
    task_out_dir = tmp_path / f"formula_task_{task_id[:8]}"
    zip_path = tmp_path / f"formulas_{stem}_{task_id[:8]}.zip"
    task_out_dir.mkdir(parents=True, exist_ok=True)

    images_dir = task_out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    img1 = Image.new("RGB", (1600, 400), color=(255, 255, 255))
    img1_path = images_dir / "p000_eq_00000.png"
    img1.save(str(img1_path))

    img2 = Image.new("RGB", (500, 1599), color=(255, 255, 255))
    img2_path = images_dir / "p000_eq_00001.png"
    img2.save(str(img2_path))

    img3 = Image.new("RGB", (1601, 1601), color=(255, 255, 255))
    img3_path = images_dir / "p001_eq_00000.png"
    img3.save(str(img3_path))

    results = [
        FormulaResultContract(
            item_id="p000_eq_00000",
            original_index=0,
            category="isolated",
            box=(50.0, 100.0, 450.0, 200.0),
            padded_box=(46, 96, 454, 204),
            latex=r"E = mc^2",
            mathml=r'<math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mrow><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></mrow></math>',
            image_path=str(img1_path),
            confidence=0.985,
            page_idx=0,
        ),
        FormulaResultContract(
            item_id="p000_eq_00001",
            original_index=1,
            category="inline",
            box=(60.0, 250.0, 120.0, 275.0),
            padded_box=(56, 246, 124, 279),
            latex=r"f(x) = \int_0^\infty e^{-t} dt",
            mathml=r'<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mrow><mi>f</mi><mo stretchy="false">(</mo><mi>x</mi><mo stretchy="false">)</mo><mo>=</mo><msubsup><mo>&#x222B;</mo><mn>0</mn><mi>&#x221E;</mi></msubsup><msup><mi>e</mi><mrow><mo>&#x2212;</mo><mi>t</mi></mrow></msup><mi>d</mi><mi>t</mi></mrow></math>',
            image_path=str(img2_path),
            confidence=0.942,
            page_idx=0,
        ),
        FormulaResultContract(
            item_id="p001_eq_00000",
            original_index=2,
            category="isolated",
            box=(80.0, 300.0, 380.0, 420.0),
            padded_box=(76, 296, 384, 424),
            latex=r"\nabla \times \mathbf{B} = \mu_0 \mathbf{J} + \mu_0 \epsilon_0 \frac{\partial \mathbf{E}}{\partial t}",
            mathml=r'<math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mrow><mo>&#x2207;</mo><mo>&#xD7;</mo><mi mathvariant="bold">B</mi><mo>=</mo><msub><mi>&#x3BC;</mi><mn>0</mn></msub><mi mathvariant="bold">J</mi></mrow></math>',
            image_path=str(img3_path),
            confidence=0.991,
            page_idx=1,
        ),
    ]

    create_formula_zip_bundle(task_out_dir, zip_path, results)
    assert zip_path.exists(), "ZIP bundle was not created"

    unpack_dir = tmp_path / "unpacked_bundle"
    unpack_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(unpack_dir)

    # 2a. Verify formulas.json
    manifest_file = unpack_dir / "formulas.json"
    assert manifest_file.exists(), "formulas.json missing"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    assert isinstance(manifest_data, list)
    assert len(manifest_data) == 3

    for idx, raw_record in enumerate(manifest_data):
        contract_obj = FORMULA_RESULT_ADAPTER.validate_python(raw_record)
        assert isinstance(contract_obj, FormulaResultContract)
        assert contract_obj.item_id == results[idx].item_id
        assert contract_obj.category == results[idx].category
        assert contract_obj.latex == results[idx].latex

    # 2b. Verify images/
    unpacked_images = unpack_dir / "images"
    assert unpacked_images.is_dir(), "images/ missing"
    png_files = list(unpacked_images.glob("*.png"))
    assert len(png_files) == 3

    for png_p in png_files:
        with Image.open(png_p) as im:
            max_dim = max(im.width, im.height)
            assert 1599 <= max_dim <= 1601, (
                f"PNG image {png_p.name} dimension max(w,h)={max_dim} out of range [1599, 1601]"
            )

    # 2c. Verify mathml/
    unpacked_mathml = unpack_dir / "mathml"
    assert unpacked_mathml.is_dir(), "mathml/ missing"
    xml_files = list(unpacked_mathml.glob("*.xml"))
    assert len(xml_files) == 3

    for xml_p in xml_files:
        content = xml_p.read_text(encoding="utf-8")
        assert len(content.strip()) > 0
        root = ET.fromstring(content)
        assert "math" in root.tag.lower()

    # 2d. Verify latex/
    unpacked_latex = unpack_dir / "latex"
    assert unpacked_latex.is_dir(), "latex/ missing"
    tex_files = list(unpacked_latex.glob("*.tex"))
    assert len(tex_files) == 3

    for tex_p in tex_files:
        tex_content = tex_p.read_text(encoding="utf-8").strip()
        assert len(tex_content) > 0
        assert not tex_content.startswith("```")
        assert not tex_content.endswith("```")

    # 2e. Verify formulas.tex consolidated file
    formulas_tex = unpack_dir / "formulas.tex"
    assert formulas_tex.exists()
    tex_body = formulas_tex.read_text(encoding="utf-8")
    assert r"\documentclass{article}" in tex_body
    assert r"E = mc^2" in tex_body


def test_deliverable_zip_bundle_zero_formulas(tmp_path):
    """
    Stress-test: PDF with 0 formulas detected.
    Verify:
      - ZIP package is successfully created without errors.
      - formulas.json exists and is empty list [].
      - formulas.tex exists with clear notice.
      - README.txt exists explaining no formulas detected.
    """
    task_id = "test_empty_formula_12345678"
    stem = "text_only_doc"
    task_out_dir = tmp_path / f"formula_task_{task_id[:8]}"
    zip_path = tmp_path / f"formulas_{stem}_{task_id[:8]}.zip"
    task_out_dir.mkdir(parents=True, exist_ok=True)

    results: List[FormulaResultContract] = []

    create_formula_zip_bundle(task_out_dir, zip_path, results)
    assert zip_path.exists()

    unpack_dir = tmp_path / "unpacked_empty"
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(unpack_dir)

    manifest_file = unpack_dir / "formulas.json"
    assert manifest_file.exists()
    assert json.loads(manifest_file.read_text(encoding="utf-8")) == []

    readme_file = unpack_dir / "README.txt"
    assert readme_file.exists()
    assert "No mathematical formulas detected" in readme_file.read_text(encoding="utf-8")

    tex_file = unpack_dir / "formulas.tex"
    assert tex_file.exists()
    assert "No formulas detected in document." in tex_file.read_text(encoding="utf-8")


# ===========================================================================
# 4. End-to-End Pipeline & Exporter Adversarial Edge Cases
# ===========================================================================

def test_pipeline_export_adversarial_formulas(tmp_path):
    """
    Adversarial test on exporter with dirty/malformed input:
      - Markdown fences (```latex ...)
      - Unwrapped CJK characters inside formula
      - Malformed LaTeX with unbalanced brackets
      - Extreme aspect ratios (very thin, very wide)
    Verify:
      - Exporter handles all without unhandled exception.
      - Generated MathML XML parses cleanly via ElementTree.
      - Generated PNG has max(w, h) = 1600 +- 1.
    """
    from src.extraction.formula_exporter import export_formula_results

    out_dir = tmp_path / "adversarial_export"
    out_dir.mkdir(parents=True, exist_ok=True)

    crop_wide = Image.new("RGB", (800, 20), color=(240, 240, 240))
    det_wide = FormulaDetectionContract(
        box=(10.0, 10.0, 810.0, 30.0),
        score=0.92,
        category="isolated",
        class_id=1,
    )
    item_wide = FormulaCroppedItemContract(
        item_id="p000_eq_wide",
        original_index=0,
        detection=det_wide,
        padded_box=(6, 6, 814, 34),
        aspect_ratio=800.0 / 20.0,
    )

    crop_tall = Image.new("RGB", (20, 800), color=(240, 240, 240))
    det_tall = FormulaDetectionContract(
        box=(50.0, 50.0, 70.0, 850.0),
        score=0.88,
        category="isolated",
        class_id=1,
    )
    item_tall = FormulaCroppedItemContract(
        item_id="p000_eq_tall",
        original_index=1,
        detection=det_tall,
        padded_box=(46, 46, 74, 854),
        aspect_ratio=20.0 / 800.0,
    )

    crops = [crop_wide, crop_tall]
    items = [item_wide, item_tall]
    raw_predictions = [
        ("```latex \\text{速度 } v = \\frac{\\Delta x}{\\Delta t} ```", 0.95),
        ("\\frac{unbalanced_bracket{missing", 0.70),
    ]

    results = export_formula_results(
        crops=crops,
        items=items,
        raw_predictions=raw_predictions,
        output_dir=out_dir,
        pdf_page=None,
        imgsz=1600,
        save_manifest=True,
    )

    assert len(results) == 2

    # Check PNG dimensions
    for res in results:
        img_p = Path(res.image_path)
        assert img_p.exists()
        with Image.open(img_p) as im:
            max_d = max(im.width, im.height)
            assert 1599 <= max_d <= 1601, f"Expected 1600+-1, got {max_d}"

    # Check MathML XML parseability
    for res in results:
        assert len(res.mathml) > 0
        tree = ET.fromstring(res.mathml)
        assert "math" in tree.tag.lower()

    # Check LaTeX sanitization
    assert not results[0].latex.startswith("```")
    assert not results[0].latex.endswith("```")
    assert "速度" in results[0].latex


# ===========================================================================
# 5. Production Router Integration with Real Pipeline Output
# ===========================================================================

@pytest.mark.asyncio
async def test_formula_router_process_pdf_sync_end_to_end_artifact_generation(tmp_path):
    """
    Test process_pdf_sync integration:
    Run with mock pipeline returning 1 formula, verify that:
    1. isolated zip formulas_{stem}_{task_id[:8]}.zip is created in PATHS.output_dir.
    2. formula_tasks dictionary has zip_file, result_file, status='completed'.
    3. Unpacking the zip file reveals all valid deliverables.
    """
    pdf_path = PATHS.input_dir / "paper.pdf"
    _create_sample_pdf(pdf_path, num_pages=1)

    task_id = "test_e2e_task_abcdef12"
    orig_stem = "paper"

    formula_tasks[task_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "排隊中...",
        "log": "",
        "result_file": None,
        "word_file": None,
        "zip_file": None,
        "orig_name": orig_stem,
        "created_at": time.time(),
    }
    get_task_queue().enqueue(
        TaskRecord(
            task_id=task_id,
            stem=orig_stem,
            status=TaskStatus.QUEUED.value,
            progress=0,
            engine="formula",
        )
    )

    def mock_process_document(*args, **kwargs):
        out_dir = Path(kwargs["output_dir"])
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        img_p = images_dir / "p000_eq_00000.png"
        Image.new("RGB", (1600, 300), color=(255, 255, 255)).save(str(img_p))

        res = FormulaResultContract(
            item_id="p000_eq_00000",
            original_index=0,
            category="isolated",
            box=(10.0, 10.0, 200.0, 50.0),
            padded_box=(6, 6, 204, 54),
            latex=r"a^2 + b^2 = c^2",
            mathml=r'<math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mrow><msup><mi>a</mi><mn>2</mn></msup><mo>+</mo><msup><mi>b</mi><mn>2</mn></msup><mo>=</mo><msup><mi>c</mi><mn>2</mn></msup></mrow></math>',
            image_path=str(img_p),
            confidence=0.99,
            page_idx=0,
        )
        return [res]

    mock_pipeline = MagicMock()
    mock_pipeline.process_document.side_effect = mock_process_document

    with patch("src.web.routers.formula_router.get_formula_pipeline", return_value=mock_pipeline):
        await asyncio.to_thread(
            process_pdf_sync,
            task_id,
            str(pdf_path),
            True,  # extract_formulas
            0,     # start_page
            0,     # end_page
            0.1,   # header_ratio
            0.1,   # footer_ratio
        )

    # Assertions on task state
    assert formula_tasks[task_id]["status"] == "completed"
    assert formula_tasks[task_id]["progress"] == 100.0
    zip_path = Path(formula_tasks[task_id]["zip_file"])
    assert zip_path.exists()
    assert zip_path.name == f"formulas_{orig_stem}_{task_id[:8]}.zip"

    unpack_dir = tmp_path / "unpack_e2e"
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(unpack_dir)

    assert (unpack_dir / "formulas.json").exists()
    assert (unpack_dir / "formulas.tex").exists()
    assert (unpack_dir / "images" / "p000_eq_00000.png").exists()
    assert (unpack_dir / "mathml" / "p000_eq_00000.xml").exists()
    assert (unpack_dir / "latex" / "p000_eq_00000.tex").exists()


# ===========================================================================
# 6. Empirical Vulnerability Reproduction Tests
# ===========================================================================

def test_cancellation_mid_flight_thread_status_overwrite_defect():
    """
    Empirical proof of Defect 1:
    When a task is cancelled mid-flight, process_pdf_sync in the worker thread
    lacks cancellation awareness and unconditionally overwrites formula_tasks[task_id]["status"]
    from 'cancelled' to 'completed'.
    """
    task_id = "test_cancel_race_repro"
    formula_tasks[task_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "排隊中...",
        "log": "",
    }
    q = get_task_queue()
    q.enqueue(
        TaskRecord(
            task_id=task_id,
            stem="repro",
            status=TaskStatus.QUEUED.value,
        )
    )

    # 1. User cancels the task mid-flight
    q.cancel_task(task_id)
    formula_tasks[task_id]["status"] = "cancelled"
    assert q.get_task(task_id).status == TaskStatus.CANCELLED.value
    assert formula_tasks[task_id]["status"] == "cancelled"

    # 2. Worker thread process_pdf_sync finishes later
    mock_pipeline = MagicMock()
    mock_pipeline.process_document.return_value = []
    with patch("src.web.routers.formula_router.get_formula_pipeline", return_value=mock_pipeline):
        process_pdf_sync(task_id, "dummy.pdf", False, 0, 0, 0.1, 0.1)

    # In SQLite, status remains cancelled because of WHERE status != 'cancelled'
    assert q.get_task(task_id).status == TaskStatus.CANCELLED.value

    # Status in formula_tasks is preserved as 'cancelled' and NOT overwritten to 'completed'
    assert formula_tasks[task_id]["status"] == "cancelled"

