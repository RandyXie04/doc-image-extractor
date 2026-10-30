# -*- coding: utf-8 -*-
"""
Formula & Preview FastAPI Router (`src/web/routers/formula_router.py`)
=====================================================================
Modularized from `src/web/app.py`.
Handles PDF upload, live crop line preview, template extraction,
and GPU-concurrency-guarded mathematical formula extraction pipeline.
"""

from __future__ import annotations

import asyncio
import io
import os
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import fitz  # PyMuPDF
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageDraw

from src.core_agent import PDFConversionAgent
from src.utils.task_queue import TaskRecord, TaskStatus, get_event_broadcaster, get_task_queue
from src.web.dependencies import (
    CFG,
    PATHS,
    get_gpu_semaphore,
    save_upload_file_safely,
    track_background_task,
)

router = APIRouter(tags=["formula_extraction"])

# Shared task dictionary for formula extraction pipeline
formula_tasks: Dict[str, Dict[str, Any]] = {}


def process_pdf_sync(
    task_id: str,
    file_path: str,
    extract_formulas: bool,
    start_page: int,
    end_page: int,
    header_ratio: float,
    footer_ratio: float,
    left_ratio: float = 0.0,
    right_ratio: float = 0.0,
    extract_inline: bool = False,
) -> None:
    """Synchronous CPU/GPU formula pipeline executed in separate worker thread."""
    queue = get_task_queue()
    try:
        formula_tasks[task_id]["status"] = "processing"
        formula_tasks[task_id]["progress"] = 5.0
        queue.update_task(task_id, status=TaskStatus.RUNNING.value, progress=5, message="初始化視覺偵測模型...")

        def progress_cb(current, total, msg):
            pct = 5.0 + (current / total) * 90.0
            formula_tasks[task_id]["progress"] = pct
            formula_tasks[task_id]["message"] = msg
            formula_tasks[task_id]["log"] += f"[{current}/{total}] {msg}\n"
            queue.update_task(task_id, progress=int(pct), message=msg)

        def log_fn(msg):
            formula_tasks[task_id]["log"] += f"{msg}\n"

        log_fn(f"[DEBUG] 轉檔配置: extract_formulas={extract_formulas}, extract_inline={extract_inline}")

        agent = PDFConversionAgent(
            input_pdf=file_path,
            header_ratio=header_ratio,
            footer_ratio=footer_ratio,
            left_ratio=left_ratio,
            right_ratio=right_ratio,
            extract_inline=extract_inline,
        )

        pipeline_res = agent.execute_pipeline(
            extract_formulas=extract_formulas,
            start_page_idx=start_page,
            end_page_idx=end_page if end_page > 0 else None,
            log_fn=log_fn,
            progress_callback=progress_cb,
        )

        if pipeline_res and pipeline_res.get("delivery_folder"):
            zip_p = pipeline_res.get("zip_path")
            formula_tasks[task_id]["word_file"] = None
            formula_tasks[task_id]["zip_file"] = zip_p
            formula_tasks[task_id]["result_file"] = zip_p
            formula_tasks[task_id]["progress"] = 100.0
            formula_tasks[task_id]["status"] = "completed"
            formula_tasks[task_id]["message"] = "處理完成"
            queue.update_task(task_id, status=TaskStatus.COMPLETED.value, progress=100, message="處理完成")
        else:
            raise Exception("未能產生有效輸出成果")

    except Exception as e:
        err_msg = f"錯誤: {str(e)}"
        formula_tasks[task_id]["status"] = "failed"
        formula_tasks[task_id]["message"] = err_msg
        formula_tasks[task_id]["log"] += f"\n發生異常：{str(e)}\n"
        queue.update_task(task_id, status=TaskStatus.FAILED.value, message=err_msg, error=str(e))


@router.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...)):
    """Upload PDF file for formula extraction or visual crop inspection."""
    orig_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if orig_ext != ".pdf":
        raise HTTPException(status_code=400, detail="公式萃取與預覽僅支援 .pdf 格式檔案")

    file_id = f"{uuid.uuid4()}.pdf"
    file_path = PATHS.input_dir / file_id

    await save_upload_file_safely(file, file_path, max_mb=CFG.max_upload_size_mb)

    total_pages = 1
    try:
        with fitz.open(file_path) as doc:
            total_pages = len(doc)
    except Exception as e:
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"無法解析此 PDF 檔案: {e}")

    orig_name = Path(file.filename).stem if file.filename else "已轉檔"
    return {"file_id": file_id, "total_pages": total_pages, "orig_name": orig_name}


@router.post("/api/upload_template")
async def upload_template(file: UploadFile = File(...)):
    """Upload custom Word .docx layout style template."""
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="僅支援上傳 .docx 格式的範本檔案")

    template_dir = PATHS.data_dir / "database_text" / "custom_templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    file_path = template_dir / "user_template.docx"
    await save_upload_file_safely(file, file_path, max_mb=CFG.max_template_size_mb)

    return {"status": "success", "message": f"範本 {file.filename} 上傳成功", "filename": file.filename}


@router.get("/api/get_current_template")
async def get_current_template():
    """Check existence of active user or system Word templates."""
    template_path = PATHS.data_dir / "database_text" / "custom_templates" / "user_template.docx"
    default_template_path = PATHS.data_dir / "database_text" / "template.docx"
    from src.utils.path_helper import get_template_path

    bundled_template_path = get_template_path()

    if template_path.exists():
        return {"has_custom": True, "name": "user_template.docx"}
    elif default_template_path.exists():
        return {"has_custom": False, "name": "系統自訂範本"}
    elif bundled_template_path.exists():
        return {"has_custom": False, "name": "系統預設範本"}
    else:
        return {"has_custom": False, "name": "無可用範本"}


@router.get("/api/get_template_styles")
async def get_template_styles():
    """Extract paragraph style names defined in the active docx template."""
    from src.utils.path_helper import get_template_path

    template_path = PATHS.data_dir / "database_text" / "custom_templates" / "user_template.docx"
    if not template_path.exists():
        template_path = PATHS.data_dir / "database_text" / "template.docx"
        if not template_path.exists():
            template_path = get_template_path()
            if not template_path.exists():
                return {"status": "error", "message": "無可用範本"}

    styles = []
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(template_path, "r") as z:
            if "word/styles.xml" in z.namelist():
                tree = ET.fromstring(z.read("word/styles.xml"))
                for s in tree.findall(f"{w_ns}style"):
                    if s.get(f"{w_ns}type") == "paragraph":
                        name_el = s.find(f"{w_ns}name")
                        if name_el is not None:
                            name_val = name_el.get(f"{w_ns}val")
                            if name_val:
                                styles.append(name_val)
    except Exception as e:
        return {"status": "error", "message": f"解析樣式失敗: {e}"}

    return {"status": "success", "styles": styles}


@router.get("/api/render_preview/{file_id}")
async def render_preview(
    file_id: str,
    page: int = 1,
    header: float = 0.1,
    footer: float = 0.1,
    left: float = 0.0,
    right: float = 0.0,
):
    """Render single PDF page with WYSIWYG crop guidelines (red/blue/green lines)."""
    file_path = PATHS.input_dir / file_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with fitz.open(file_path) as doc:
            page_idx = max(0, min(page - 1, len(doc) - 1))
            page_obj: Any = doc[page_idx]

            pix = page_obj.get_pixmap(dpi=72)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            draw = ImageDraw.Draw(img)
            w, h = img.size
            y_header = int(h * header)
            y_footer = int(h * (1.0 - footer))
            x_left = int(w * left)
            x_right = int(w * (1.0 - right))

            draw.line([(0, y_header), (w, y_header)], fill="red", width=2)
            draw.line([(0, y_footer), (w, y_footer)], fill="blue", width=2)

            if x_left > 0:
                draw.line([(x_left, 0), (x_left, h)], fill="green", width=2)
            if right > 0:
                draw.line([(x_right, 0), (x_right, h)], fill="green", width=2)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            buf.seek(0)

            return StreamingResponse(buf, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/process")
async def start_process(
    background_tasks: BackgroundTasks,
    file_id: str = Form(...),
    extract_formulas: bool = Form(True),
    start_page: int = Form(0),
    end_page: int = Form(0),
    header_ratio: float = Form(0.1),
    footer_ratio: float = Form(0.1),
    left_ratio: float = Form(0.0),
    right_ratio: float = Form(0.0),
    extract_inline: bool = Form(False),
    orig_name: str = Form(""),
):
    """
    Queue AI formula extraction under GPU Concurrency Lock.
    Prevents parallel inference with OCR pipeline, avoiding CUDA OOM on 12GB RTX 3060.
    """
    file_path = PATHS.input_dir / file_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    task_id = str(uuid.uuid4())
    formula_tasks[task_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "排隊中，等待 GPU 資源釋放...",
        "log": "任務已加入佇列...\n",
        "result_file": None,
        "word_file": None,
        "zip_file": None,
        "orig_name": orig_name or "已轉檔",
        "created_at": time.time(),
    }

    queue = get_task_queue()
    queue.enqueue(
        TaskRecord(
            task_id=task_id,
            stem=orig_name or Path(file_id).stem,
            status=TaskStatus.QUEUED.value,
            progress=0,
            message="排隊中，等待 GPU 資源釋放...",
            engine="formula",
            payload={"file_path": str(file_path)},
        )
    )

    async def _guarded_runner():
        async with get_gpu_semaphore():
            await asyncio.to_thread(
                process_pdf_sync,
                task_id,
                str(file_path),
                extract_formulas,
                start_page,
                end_page,
                header_ratio,
                footer_ratio,
                left_ratio,
                right_ratio,
                extract_inline,
            )

    t = asyncio.create_task(_guarded_runner())
    track_background_task(t)

    return {"task_id": task_id}


@router.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """Retrieve status of formula extraction task."""
    if task_id in formula_tasks:
        return formula_tasks[task_id]
    rec = get_task_queue().get_task(task_id)
    if rec:
        return {
            "status": rec.status,
            "progress": float(rec.progress),
            "message": rec.message,
            "log": rec.message,
            "created_at": rec.created_at,
        }
    return {"status": "not_found"}


@router.get("/api/download/{task_id}")
async def download_result(task_id: str):
    """Download result file from formula or OCR task."""
    if task_id in formula_tasks and formula_tasks[task_id].get("result_file"):
        path = formula_tasks[task_id]["result_file"]
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="檔案不存在或已超過 24 小時保存期限由系統自動銷毀")
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if path.endswith(".docx") else "application/zip"
        return FileResponse(path, media_type=media_type, filename=os.path.basename(path))
    raise HTTPException(status_code=404, detail="成果檔案不存在或任務未完成")


@router.get("/api/download/{task_id}/formulas")
async def download_formulas(task_id: str):
    """Download formula images zip bundle."""
    if task_id in formula_tasks and formula_tasks[task_id].get("zip_file"):
        path = formula_tasks[task_id]["zip_file"]
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="檔案不存在或已超過 24 小時保存期限由系統自動銷毀")
        return FileResponse(path, media_type="application/zip", filename=os.path.basename(path))
    raise HTTPException(status_code=404, detail="公式圖檔包不存在或任務未完成")
