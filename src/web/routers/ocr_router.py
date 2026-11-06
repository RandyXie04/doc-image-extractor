# -*- coding: utf-8 -*-
"""
OCR Pipeline & Layout Reconstruction FastAPI Router (`src/web/routers/ocr_router.py`)
====================================================================================
Modularized from `src/web/app.py`.
Manages OCR subprocess execution, real-time progress tracking, font mapping,
and Word/Markdown output generation under the global GPU concurrency lock.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import fitz  # PyMuPDF
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from src.utils.task_queue import TaskRecord, TaskStatus, get_event_broadcaster, get_task_queue
from src.web.dependencies import (
    CFG,
    PATHS,
    get_gpu_semaphore,
    save_upload_file_safely,
    track_background_task,
)
from src.web.schemas import OcrProgressResponse, OcrRunStartResponse

logger = logging.getLogger("ocr_router")
router = APIRouter(tags=["ocr_pipeline"])


def _emit_font_suggest_diag(log_line: str) -> None:
    """Emit a single-line diagnostic log to both standard logger and CMD stdout."""
    logger.info(log_line)
    print(log_line, flush=True)

# Shared in-memory OCR progress tracking for backward-compatible polling
ocr_progress_dict: Dict[str, Dict[str, Any]] = {}


class MarkdownUpdate(BaseModel):
    content: str


def is_meaningful_progress_line(line: str) -> bool:
    """
    Filters subprocess stdout lines so third-party library warnings (PyTorch, Surya, Pandoc)
    or Python tracebacks do not overwrite structured UI progress messages.
    """
    s = (line or "").strip()
    if not s:
        return False
    noise_prefixes = (
        "Traceback ",
        'File "',
        "UserWarning:",
        "FutureWarning:",
        "DeprecationWarning:",
        "RuntimeWarning:",
        "warnings.warn(",
    )
    if s.startswith(noise_prefixes) or "site-packages" in s:
        return False
    progress_markers = (
        "[INFO]",
        "[WARN]",
        "[ERROR]",
        "[PROGRESS]",
        "[STAGE]",
        "[EngineDispatcher]",
        "[FontMap]",
        "[AI-Kaiti]",
        "Page ",
        "頁",
        "完成",
        "提取",
        "建構",
        "正在",
        "處理",
    )
    return any(m in s for m in progress_markers)


@router.get("/api/ocr_progress/{filename_stem}", response_model=OcrProgressResponse)
async def get_ocr_progress(filename_stem: str) -> OcrProgressResponse:
    """Polling endpoint for OCR pipeline progress."""
    progress = ocr_progress_dict.get(filename_stem)
    if progress is None:
        try:
            queue = get_task_queue()
            rec = queue.get_task_by_stem(filename_stem)
            if rec:
                progress = {
                    "task_id": rec.task_id,
                    "progress": rec.progress,
                    "message": rec.message,
                    "status": rec.status,
                    "error": rec.error,
                }
        except Exception:
            pass
    if progress is None:
        progress = {"task_id": None, "progress": 0, "message": "Waiting...", "status": "processing", "error": None}
    return OcrProgressResponse(**progress)


@router.get("/api/ocr_events/{filename_stem}")
async def stream_ocr_events(filename_stem: str):
    """
    Server-Sent Events (SSE) streaming endpoint for real-time OCR progress.
    Eliminates client-side polling delays and database lock contention.
    """
    broadcaster = get_event_broadcaster()
    queue = get_task_queue()
    rec = queue.get_task_by_stem(filename_stem)
    task_id = rec.task_id if rec else ocr_progress_dict.get(filename_stem, {}).get("task_id")

    async def event_generator():
        if not task_id:
            if filename_stem in ocr_progress_dict:
                yield f"data: {_json.dumps(ocr_progress_dict[filename_stem], ensure_ascii=False)}\n\n"
            return

        sub_queue = broadcaster.subscribe(task_id)
        try:
            # Emit current known state first
            if rec:
                yield f"data: {_json.dumps(rec.to_dict(), ensure_ascii=False)}\n\n"
                if rec.status in ("completed", "failed", "cancelled"):
                    return
            elif filename_stem in ocr_progress_dict:
                yield f"data: {_json.dumps(ocr_progress_dict[filename_stem], ensure_ascii=False)}\n\n"
                if ocr_progress_dict[filename_stem].get("status") in ("completed", "failed", "cancelled"):
                    return

            while True:
                try:
                    data = await asyncio.wait_for(sub_queue.get(), timeout=15.0)
                    yield f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"
                    if data.get("status") in ("completed", "failed", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(sub_queue, task_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/upload_and_run_ocr", response_model=OcrRunStartResponse)
async def upload_and_run_ocr(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None),
    file_id: str = Form(None),
    filename_orig: str = Form(None),
    style_mapping: str = Form(None),
    engine: str = Form("auto"),
    header_ratio: float = Form(0.1),
    footer_ratio: float = Form(0.1),
    left_ratio: float = Form(0.0),
    right_ratio: float = Form(0.0),
    start_page: int = Form(0),
    end_page: int = Form(0),
    no_footnote: bool = Form(True),
    ai_kaiti: bool = Form(False),
    ai_kaiti_threshold: float = Form(0.65),
) -> OcrRunStartResponse:
    """Launch full-automatic OCR layout pipeline under GPU concurrency guard."""
    pdf_dir = PATHS.root / "data" / "database_text"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    if file_id and (PATHS.input_dir / file_id).exists():
        raw_pdf_path = PATHS.input_dir / file_id
        filename_stem = filename_orig or Path(file_id).stem
    elif file and file.filename:
        clean_filename = Path(file.filename).name
        ext = os.path.splitext(clean_filename)[1].lower()
        if ext != ".pdf":
            raise HTTPException(status_code=400, detail="僅支援 PDF 檔案格式")
        raw_pdf_path = pdf_dir / clean_filename
        await save_upload_file_safely(file, raw_pdf_path, max_mb=CFG.max_upload_size_mb)
        filename_stem = Path(clean_filename).stem
    else:
        raise HTTPException(status_code=400, detail="請提供 PDF 檔案或檔案代碼")

    task_id = str(uuid.uuid4())
    input_pdf_path = raw_pdf_path
    if header_ratio > 0 or footer_ratio > 0 or left_ratio > 0 or right_ratio > 0 or start_page > 0 or end_page > 0:
        cropped_pdf_path = pdf_dir / f"cropped_{filename_stem}_{task_id[:8]}.pdf"
        try:
            with fitz.open(raw_pdf_path) as doc:
                total_pages = len(doc)
                s_page = max(1, start_page) if start_page > 0 else 1
                e_page = min(total_pages, end_page) if end_page > 0 else total_pages

                if s_page > 1 or e_page < total_pages:
                    doc.select(range(s_page - 1, e_page))

                for page in doc:
                    if header_ratio > 0 or footer_ratio > 0 or left_ratio > 0 or right_ratio > 0:
                        rect = page.rect
                        y_top = rect.height * max(0.0, min(header_ratio, 0.49))
                        f_r = footer_ratio if footer_ratio < 0.5 else (1.0 - footer_ratio)
                        y_bottom = rect.height * (1.0 - max(0.0, min(f_r, 0.49)))
                        x_left = rect.width * max(0.0, min(left_ratio, 0.49))
                        r_r = right_ratio if right_ratio < 0.5 else (1.0 - right_ratio)
                        x_right = rect.width * (1.0 - max(0.0, min(r_r, 0.49)))
                        page.set_cropbox(fitz.Rect(x_left, y_top, x_right, y_bottom))
                doc.save(cropped_pdf_path)
            input_pdf_path = cropped_pdf_path
        except Exception as crop_err:
            print(f"[Warning] PDF pre-crop/page-range failed: {crop_err}")
            input_pdf_path = raw_pdf_path

    queue = get_task_queue()
    queue.enqueue(
        TaskRecord(
            task_id=task_id,
            stem=filename_stem,
            status=TaskStatus.QUEUED.value,
            progress=0,
            message="正在初始化任務並排入佇列...",
            engine=engine,
            payload={
                "file_path": str(input_pdf_path),
                "raw_pdf_path": str(raw_pdf_path),
                "file_id": file_id or "",
                "ai_kaiti": ai_kaiti,
                "ai_kaiti_threshold": ai_kaiti_threshold,
                "no_footnote": no_footnote,
            },
        )
    )

    ocr_progress_dict[filename_stem] = {
        "task_id": task_id,
        "progress": 0,
        "message": "正在初始化任務...",
        "status": "processing",
        "raw_pdf_path": str(raw_pdf_path),
        "file_id": file_id or "",
        "created_at": time.time(),
    }

    async def run_scripts_async(tid, pdf_path_str, stem, style_map_json, eng, skip_footnotes, ai_kaiti_on, ai_kaiti_thresh):
        from collections import deque

        style_map_file_path: Path | None = None
        try:
            curr_rec = queue.get_task(tid)
            if curr_rec and curr_rec.status == TaskStatus.CANCELLED.value:
                ocr_progress_dict[stem]["status"] = "cancelled"
                ocr_progress_dict[stem]["message"] = "任務已由使用者取消"
                return

            ocr_progress_dict[stem]["message"] = "已排入轉檔佇列，等待運算資源..."
            queue.update_task(tid, status=TaskStatus.RUNNING.value, message="已排入轉檔佇列，等待運算資源...")
            async with get_gpu_semaphore():
                curr_rec = queue.get_task(tid)
                if curr_rec and curr_rec.status == TaskStatus.CANCELLED.value:
                    ocr_progress_dict[stem]["status"] = "cancelled"
                    ocr_progress_dict[stem]["message"] = "任務已由使用者取消"
                    return

                output_dir = PATHS.root / "data" / "03_output"
                backup_dir = output_dir / "backup_originals"
                output_dir.mkdir(parents=True, exist_ok=True)

                md_file = output_dir / f"{stem}.md"
                docx_file = output_dir / f"{stem}.docx"

                for f_path in [md_file, docx_file]:
                    if f_path.exists():
                        backup_dir.mkdir(parents=True, exist_ok=True)
                        backup_path = backup_dir / f"{f_path.stem}_{int(time.time())}_{tid[:6]}{f_path.suffix}"
                        try:
                            shutil.move(str(f_path), str(backup_path))
                        except Exception:
                            pass

                cmd = [
                    sys.executable,
                    "-m",
                    "src.scripts.pdf_engine_dispatcher",
                    "--file",
                    pdf_path_str,
                    "--output_dir",
                    str(output_dir),
                    "--output_stem",
                    stem,
                    "--engine",
                    eng,
                ]
                if skip_footnotes:
                    cmd.append("--no_footnote")
                if ai_kaiti_on:
                    cmd.extend(["--ai_kaiti", "--ai_kaiti_threshold", str(ai_kaiti_thresh)])
                if style_map_json:
                    temp_sm_dir = PATHS.root / "data" / "temp_uploads"
                    temp_sm_dir.mkdir(parents=True, exist_ok=True)
                    style_map_file_path = temp_sm_dir / f"style_mapping_{tid}.json"
                    style_map_file_path.write_text(style_map_json, encoding="utf-8")
                    cmd.extend(["--style_mapping_file", str(style_map_file_path)])

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(PATHS.root),
                )
                queue.register_runtime_handles(tid, proc=proc)

                recent_error_lines: deque[str] = deque(maxlen=10)
                if proc.stdout is not None:
                    async for raw_line in proc.stdout:
                        try:
                            line = raw_line.decode("utf-8", errors="replace").strip()
                        except Exception:
                            line = ""
                        if line:
                            if line.startswith("{") and "progress" in line:
                                try:
                                    data = _json.loads(line)
                                    prog = int(data.get("progress", ocr_progress_dict[stem]["progress"]))
                                    msg = data.get("message", line)
                                    ocr_progress_dict[stem]["progress"] = prog
                                    ocr_progress_dict[stem]["message"] = msg
                                    queue.update_task(tid, progress=prog, message=msg)
                                    if any(k in msg for k in ("[ERROR]", "[FATAL]", "失敗", "失败", "Exception", "Error")):
                                        recent_error_lines.append(msg[:200])
                                except Exception:
                                    pass
                            elif is_meaningful_progress_line(line):
                                short_msg = line[:120]
                                ocr_progress_dict[stem]["message"] = short_msg
                                queue.update_task(tid, message=short_msg)
                                if any(k in line for k in ("[ERROR]", "[FATAL]", "失敗", "失败", "Exception", "Error")):
                                    recent_error_lines.append(line[:200])
                            elif not line.startswith(("UserWarning:", "FutureWarning:", "DeprecationWarning:", "RuntimeWarning:", "warnings.warn(")):
                                if any(k in line for k in ("Error", "Exception", "[ERROR]", "[FATAL]", "失敗", "失败")):
                                    recent_error_lines.append(line[:200])

                await proc.wait()

                curr_rec = queue.get_task(tid)
                if curr_rec and curr_rec.status == TaskStatus.CANCELLED.value:
                    ocr_progress_dict[stem]["status"] = "cancelled"
                    ocr_progress_dict[stem]["message"] = "任務已由使用者取消"
                    return

                if proc.returncode != 0:
                    last_msg = ocr_progress_dict[stem].get("message", "")
                    err_summary = recent_error_lines[-1] if recent_error_lines else last_msg
                    fail_msg = f"轉檔程序執行失敗 (代碼: {proc.returncode})"
                    if err_summary and not err_summary.startswith("{") and "轉檔程序執行失敗" not in err_summary:
                        fail_msg = f"{fail_msg}: {err_summary}"
                    ocr_progress_dict[stem]["status"] = "failed"
                    ocr_progress_dict[stem]["message"] = fail_msg
                    queue.update_task(
                        tid,
                        status=TaskStatus.FAILED.value,
                        message=fail_msg,
                        error=f"Process exited with {proc.returncode}: {err_summary}",
                    )
                    return

                if not md_file.exists():
                    fail_msg = "轉檔程序異常結束：未生成 Markdown 輸出檔案"
                    ocr_progress_dict[stem]["status"] = "failed"
                    ocr_progress_dict[stem]["message"] = fail_msg
                    queue.update_task(tid, status=TaskStatus.FAILED.value, message=fail_msg, error=fail_msg)
                    return

                docx_msg = "正在套用樣式並產生 Word (.docx) 文件..."
                ocr_progress_dict[stem]["progress"] = 92
                ocr_progress_dict[stem]["message"] = docx_msg
                queue.update_task(tid, progress=92, message=docx_msg)

                md_proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "src.scripts.md_to_docx",
                    "--files",
                    str(md_file),
                    "--skip-text-postprocess",
                    cwd=str(PATHS.root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                queue.register_runtime_handles(tid, proc=md_proc)
                _, md_err = await md_proc.communicate()

                curr_rec = queue.get_task(tid)
                if curr_rec and curr_rec.status == TaskStatus.CANCELLED.value:
                    ocr_progress_dict[stem]["status"] = "cancelled"
                    ocr_progress_dict[stem]["message"] = "任務已由使用者取消"
                    return

                if md_proc.returncode != 0 or not docx_file.exists():
                    err_detail = md_err.decode(errors="replace").strip() if md_err else ""
                    fail_msg = f"Word (.docx) 文件產生失敗: {err_detail[:150]}" if err_detail else "Word (.docx) 文件產生失敗"
                    ocr_progress_dict[stem]["status"] = "failed"
                    ocr_progress_dict[stem]["message"] = fail_msg
                    queue.update_task(tid, status=TaskStatus.FAILED.value, message=fail_msg, error=fail_msg)
                    return

                ocr_progress_dict[stem]["progress"] = 100
                ocr_progress_dict[stem]["message"] = "轉檔完成！"
                ocr_progress_dict[stem]["status"] = "completed"
                queue.update_task(tid, status=TaskStatus.COMPLETED.value, progress=100, message="轉檔完成！")
        except asyncio.CancelledError:
            ocr_progress_dict[stem]["status"] = "cancelled"
            ocr_progress_dict[stem]["message"] = "任務已由使用者取消"
            raise
        except Exception as err:
            err_msg = f"處理過程異常: {str(err)}"
            ocr_progress_dict[stem]["status"] = "failed"
            ocr_progress_dict[stem]["message"] = err_msg
            queue.update_task(tid, status=TaskStatus.FAILED.value, message=err_msg, error=str(err))
        finally:
            queue.unregister_runtime_handles(tid)
            if style_map_file_path is not None and style_map_file_path.exists():
                try:
                    style_map_file_path.unlink()
                except Exception:
                    pass
            if "cropped_" in os.path.basename(pdf_path_str) and os.path.exists(pdf_path_str):
                try:
                    os.unlink(pdf_path_str)
                except Exception:
                    pass

    t = asyncio.create_task(
        run_scripts_async(
            task_id,
            str(input_pdf_path),
            filename_stem,
            style_mapping,
            engine,
            no_footnote,
            ai_kaiti,
            ai_kaiti_threshold,
        )
    )
    queue.register_runtime_handles(task_id, task=t)
    track_background_task(t)

    return OcrRunStartResponse(message="OCR 管道已成功啟動", filename_stem=filename_stem, task_id=task_id)


@router.get("/api/download_ocr_result/{filename_stem}/{ext}")
async def download_ocr_result(filename_stem: str, ext: str):
    """Download converted Word docx or Markdown md file."""
    ext = ext.lower().lstrip(".")
    if ext not in ["docx", "md"]:
        raise HTTPException(status_code=400, detail="不支援的檔案格式")

    output_dir = PATHS.root / "data" / "03_output"
    file_path = output_dir / f"{filename_stem}.{ext}"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="檔案不存在或已過期")

    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == "docx" else "text/markdown; charset=utf-8"
    return FileResponse(path=str(file_path), media_type=media_type, filename=f"{filename_stem}.{ext}")


@router.get("/api/get_markdown/{filename_stem}")
async def get_markdown(filename_stem: str):
    """Retrieve Markdown text for outline editor inspection."""
    output_dir = PATHS.root / "data" / "03_output"
    md_file = output_dir / f"{filename_stem}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Markdown 檔案不存在")
    content = md_file.read_text(encoding="utf-8")
    return {"filename_stem": filename_stem, "content": content}


@router.post("/api/update_and_rebuild_docx/{filename_stem}")
async def update_and_rebuild_docx(filename_stem: str, update: MarkdownUpdate):
    """Save modified Markdown content and re-trigger Word document conversion."""
    output_dir = PATHS.root / "data" / "03_output"
    md_file = output_dir / f"{filename_stem}.md"
    docx_file = output_dir / f"{filename_stem}.docx"

    md_file.write_text(update.content, encoding="utf-8")

    md_proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "src.scripts.md_to_docx",
        "--files",
        str(md_file),
        cwd=str(PATHS.root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, md_err = await md_proc.communicate()

    if md_proc.returncode != 0 or not docx_file.exists():
        err_detail = md_err.decode(errors="replace").strip() if md_err else ""
        raise HTTPException(status_code=500, detail=f"Word (.docx) 重新產生失敗: {err_detail[:150]}")

    return {"status": "success", "message": "已成功更新 Markdown 並重新套用樣式產生 Word 文件！"}


@router.post("/api/scan_fonts")
async def scan_fonts(request: Request):
    """
    掃描 PDF 字型與 template.docx 段落樣式。
    前端在「字體審查」Modal 開啟前點擊調用。
    Body JSON: { "file_id": "...", "filename_orig": "..." }
    """
    from src.scripts.pdf_font_analyzer import analyze_pdf_for_ui
    from src.utils.path_helper import get_template_path

    data = await request.json()
    file_id: str = data.get("file_id", "")
    filename_orig: str = data.get("filename_orig", "")

    pdf_path = None
    if file_id:
        candidate = PATHS.input_dir / file_id
        if candidate.exists():
            pdf_path = str(candidate)

    if not pdf_path and filename_orig:
        candidate2 = PATHS.root / "data" / "database_text" / filename_orig
        if Path(candidate2).exists():
            pdf_path = str(candidate2)

    if not pdf_path:
        raise HTTPException(status_code=404, detail="找不到 PDF 檔案，請先上傳 PDF。")

    template_candidates = [
        PATHS.data_dir / "database_text" / "custom_templates" / "user_template.docx",
        PATHS.data_dir / "database_text" / "template.docx",
        get_template_path(),
    ]
    template_path = None
    for tc in template_candidates:
        if Path(str(tc)).exists():
            template_path = str(tc)
            break

    fonts_json_path = str(PATHS.fonts_json_path)

    try:
        result = await asyncio.to_thread(
            analyze_pdf_for_ui,
            pdf_path,
            template_path,
            fonts_json_path,
        )
        return result
    except Exception as e:
        from src.scripts.gemma_layout_assistant import sanitize_diagnostic_text
        safe_err = sanitize_diagnostic_text(e)
        raise HTTPException(status_code=500, detail=f"字型分析失敗 ({type(e).__name__}): {safe_err}")


@router.post("/api/suggest_font_mappings")
async def suggest_font_mappings(request: Request):
    """
    按需觸發 Gemma 針對 PDF 字體群組與 DOCX 範本樣式提供角色與樣式建議。
    - 8K context (num_ctx=8192)
    - 序列批次推論
    - 受全域 GPU semaphore 排程保護，不與 Surya OCR 並行推論
    - 輸出隱私安全之單行 CMD 診斷紀錄（開始與結束狀態、模型、群組數、有效建議數、低信心數、耗時）
    """
    from src.scripts.gemma_layout_assistant import (
        DEFAULT_GEMMA_MODEL,
        GEMMA_FONT_NUM_CTX,
        format_font_suggestion_diag_log,
        resolve_font_suggestion_outcome,
        sanitize_diagnostic_text,
        suggest_pdf_font_group_mappings,
    )
    from src.scripts.pdf_font_analyzer import scan_pdf_fonts
    from src.utils.docx_style_profiles import read_docx_style_profiles
    from src.utils.path_helper import get_template_path

    req_id = uuid.uuid4().hex[:8]
    start_ts = time.perf_counter()
    model = CFG.ai_layout_model or DEFAULT_GEMMA_MODEL

    data = await request.json()
    file_id: str = data.get("file_id", "")
    filename_orig: str = data.get("filename_orig", "")
    supplied_fonts = data.get("fonts")
    supplied_styles = data.get("docx_style_profiles")

    if isinstance(supplied_fonts, list) and supplied_fonts:
        font_groups = supplied_fonts
    else:
        pdf_path = None
        if file_id:
            candidate = PATHS.input_dir / file_id
            if candidate.exists():
                pdf_path = str(candidate)
        if not pdf_path and filename_orig:
            candidate2 = PATHS.root / "data" / "database_text" / filename_orig
            if Path(candidate2).exists():
                pdf_path = str(candidate2)
        if not pdf_path:
            elapsed_ms = int(round((time.perf_counter() - start_ts) * 1000))
            _emit_font_suggest_diag(
                format_font_suggestion_diag_log("start", req_id=req_id, model=model, total_groups=0, template_styles=0)
            )
            _emit_font_suggest_diag(
                format_font_suggestion_diag_log(
                    "end",
                    req_id=req_id,
                    model=model,
                    total_groups=0,
                    status="request_error",
                    valid_suggestions=0,
                    low_confidence=0,
                    elapsed_ms=elapsed_ms,
                    error_type="FileNotFoundError",
                    error_msg="PDF file not found",
                )
            )
            raise HTTPException(status_code=404, detail="找不到 PDF 檔案，請先上傳 PDF。")
        font_groups = await asyncio.to_thread(scan_pdf_fonts, pdf_path)

    if isinstance(supplied_styles, list):
        docx_style_profiles = supplied_styles
    else:
        template_candidates = [
            PATHS.data_dir / "database_text" / "custom_templates" / "user_template.docx",
            PATHS.data_dir / "database_text" / "template.docx",
            get_template_path(),
        ]
        template_path = None
        for tc in template_candidates:
            if Path(str(tc)).exists():
                template_path = str(tc)
                break
        docx_style_profiles = []
        if template_path:
            try:
                docx_style_profiles = await asyncio.to_thread(read_docx_style_profiles, template_path)
            except Exception:
                docx_style_profiles = []

    total_groups = len(font_groups) if isinstance(font_groups, list) else 0
    _emit_font_suggest_diag(
        format_font_suggestion_diag_log(
            "start",
            req_id=req_id,
            model=model,
            total_groups=total_groups,
            template_styles=len(docx_style_profiles),
        )
    )

    try:
        async with get_gpu_semaphore():
            result = await asyncio.to_thread(
                suggest_pdf_font_group_mappings,
                font_groups=font_groups,
                docx_styles=docx_style_profiles,
                model=model,
                num_ctx=GEMMA_FONT_NUM_CTX,
            )
    except Exception as exc:
        elapsed_ms = int(round((time.perf_counter() - start_ts) * 1000))
        err_type = type(exc).__name__
        safe_err = sanitize_diagnostic_text(exc)
        _emit_font_suggest_diag(
            format_font_suggestion_diag_log(
                "end",
                req_id=req_id,
                model=model,
                total_groups=total_groups,
                status="inference_failed",
                valid_suggestions=0,
                low_confidence=0,
                elapsed_ms=elapsed_ms,
                error_type=err_type,
                error_msg=safe_err,
            )
        )
        return {
            "req_id": req_id,
            "status": "inference_failed",
            "outcome": "failed",
            "model": model,
            "num_ctx": GEMMA_FONT_NUM_CTX,
            "elapsed_ms": elapsed_ms,
            "message": "Gemma 推論失敗；已保留既有規則建議與人工選擇。",
            "stats": {
                "total_groups": total_groups,
                "valid_suggestions": 0,
                "low_confidence": 0,
                "elapsed_ms": elapsed_ms,
            },
            "error_type": err_type,
            "sanitized_error": safe_err,
            "suggestions": {
                str(g.get("name", "")): {
                    "font_name": str(g.get("name", "")),
                    "role": None,
                    "docx_style": None,
                    "confidence": None,
                    "reason": "Gemma 推論異常，保留規則與人工設定",
                    "status": "failed",
                    "source": "deterministic",
                }
                for g in (font_groups or [])
                if isinstance(g, dict) and g.get("name")
            },
        }

    elapsed_ms = int(round((time.perf_counter() - start_ts) * 1000))
    status = str(result.get("status") or "inference_failed")
    suggestions_map = result.get("suggestions") or {}
    stats = result.get("stats")
    if not isinstance(stats, dict):
        valid_cnt = sum(1 for v in suggestions_map.values() if isinstance(v, dict) and v.get("status") == "suggested")
        low_cnt = sum(1 for v in suggestions_map.values() if isinstance(v, dict) and v.get("status") == "low_confidence")
        stats = {
            "total_groups": total_groups,
            "valid_suggestions": valid_cnt,
            "low_confidence": low_cnt,
        }
    stats["elapsed_ms"] = elapsed_ms
    result["stats"] = stats
    result["req_id"] = req_id
    result["elapsed_ms"] = elapsed_ms
    result["outcome"] = result.get("outcome") or resolve_font_suggestion_outcome(status)

    _emit_font_suggest_diag(
        format_font_suggestion_diag_log(
            "end",
            req_id=req_id,
            model=str(result.get("model") or model),
            total_groups=stats.get("total_groups", total_groups),
            status=status,
            valid_suggestions=stats.get("valid_suggestions", 0),
            low_confidence=stats.get("low_confidence", 0),
            elapsed_ms=elapsed_ms,
            error_type=result.get("error_type"),
            error_msg=result.get("sanitized_error"),
        )
    )
    return result


@router.post("/api/save_font_mapping")
async def save_font_mapping_endpoint(request: Request):
    """
    儲存人工審查後的字型 -> 樣式 fonts.json。
    Body JSON: { "mapping": { "FontName": {"role": "H2", "docx_style": "標題 2"}, ... }, "remove_keys": ["FontName", ...] }
    """
    from src.scripts.gemma_layout_assistant import sanitize_diagnostic_text
    from src.scripts.pdf_font_analyzer import save_fonts_json

    data = await request.json()
    mapping_raw: dict = data.get("mapping", {})
    remove_keys: list = data.get("remove_keys", [])

    if not mapping_raw and not remove_keys:
        return {"status": "success", "saved": 0, "message": "無變更項目需要儲存"}

    mapping = {}
    for font_name, info in mapping_raw.items():
        mapping[font_name] = {
            "role": info.get("role"),
            "docx_style": info.get("docx_style"),
            "mapped_by": "user",
        }

    fonts_json_path = str(PATHS.fonts_json_path)
    try:
        save_fonts_json(fonts_json_path, mapping, remove_keys=remove_keys)
    except Exception as e:
        safe_err = sanitize_diagnostic_text(e)
        raise HTTPException(status_code=500, detail=f"儲存 fonts.json 失敗 ({type(e).__name__}): {safe_err}")

    return {
        "status": "success",
        "saved": len(mapping),
        "removed": len(remove_keys),
        "message": f"已儲存字體樣式對應設定（更新 {len(mapping)} 筆，重置 {len(remove_keys)} 筆）",
    }
