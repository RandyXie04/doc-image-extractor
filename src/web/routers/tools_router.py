# -*- coding: utf-8 -*-
"""
Desktop Utilities & Native Bridge FastAPI Router (`src/web/routers/tools_router.py`)
===================================================================================
Modularized from `src/web/app.py`.
Provides lossless image extraction, native Windows Explorer opening,
and user-directed local file saving.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from src.web.dependencies import CFG, PATHS, save_upload_file_safely
from src.web.schemas import ExtractImagesResponse

router = APIRouter(tags=["tools"])

# In-memory tracking for extracted images
extracted_image_tasks: Dict[str, Dict[str, Any]] = {}


@router.post("/api/extract_images", response_model=ExtractImagesResponse)
async def api_extract_images(file: UploadFile = File(...), to_grayscale: bool = Form(False)) -> ExtractImagesResponse:
    """Extract embedded images from docx or pdf file."""
    from src.scripts.extract_images import process_document_images

    orig_filename = file.filename or "document"
    orig_ext = Path(orig_filename).suffix.lower()
    if orig_ext not in [".docx", ".pdf"]:
        raise HTTPException(status_code=400, detail="僅支援 .docx 與 .pdf 檔案格式")

    task_id = str(uuid.uuid4())
    temp_dir = PATHS.root / "scratch" / f"extract_{task_id}"
    input_file_path = temp_dir / orig_filename
    extracted_folder = temp_dir / "images"
    output_zip_name = f"{Path(orig_filename).stem}_extracted_images.zip"
    output_zip_path = PATHS.root / "data" / "03_output" / output_zip_name

    temp_dir.mkdir(parents=True, exist_ok=True)
    await save_upload_file_safely(file, input_file_path, max_mb=CFG.max_upload_size_mb)

    try:
        count, zip_path = await asyncio.to_thread(
            process_document_images,
            file_path=str(input_file_path),
            output_zip_path=str(output_zip_path),
            temp_dir=str(extracted_folder),
            to_grayscale=to_grayscale,
        )

        actual_files = 0
        if extracted_folder.exists():
            actual_files = len([f for f in extracted_folder.iterdir() if f.is_file()])

        if actual_files == 0:
            count = 0

        if count == 0:
            return ExtractImagesResponse(
                success=False,
                count=0,
                message="未在此文件中偵測到任何內嵌圖片，或提取過程未產出任何圖檔。",
            )

        extracted_image_tasks[task_id] = {
            "zip_path": zip_path,
            "filename": output_zip_name,
            "count": actual_files,
            "created_at": time.time(),
        }

        return ExtractImagesResponse(
            success=True,
            count=actual_files,
            download_url=f"/api/download_extracted_images/{task_id}",
            filename=output_zip_name,
            source_path=f"data/03_output/{output_zip_name}",
            message=f"成功提取 {actual_files} 張圖片！",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"圖片提取失敗: {str(e)}")
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


@router.get("/api/download_extracted_images/{task_id}")
async def download_extracted_images(task_id: str):
    """Download image extraction result zip bundle."""
    if task_id in extracted_image_tasks:
        info = extracted_image_tasks[task_id]
        zip_path = info["zip_path"]
        if os.path.exists(zip_path):
            return FileResponse(zip_path, media_type="application/zip", filename=info["filename"])
    raise HTTPException(status_code=404, detail="檔案不存在或已過期")


@router.post("/api/open_folder/{task_id}")
async def open_folder(task_id: str, request: Request):
    """Open Explorer to extracted images folder."""
    target_path = None
    if task_id in extracted_image_tasks:
        target_path = extracted_image_tasks[task_id].get("zip_path")

    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="資料夾或檔案不存在")

    client_host = request.client.host if request.client else ""
    is_local = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
    if not is_local:
        return {"status": "fallback", "message": "遠端連線無法開啟伺服器資料夾，請改用瀏覽器下載。"}

    try:
        norm_path = os.path.normpath(str(target_path))
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", norm_path])
            return {"status": "success", "message": "已開啟檔案位置"}
        return {"status": "fallback", "message": "非 Windows 環境無法開啟伺服器檔案總管，請改用瀏覽器下載。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟資料夾: {str(e)}")


@router.post("/api/native_save_file")
async def native_save_file(request: Request):
    """Save server output file via native OS Save-As dialog or explicit local destination path."""
    data = await request.json()
    source_rel_path = (data.get("source_path") or "").strip()
    destination_path = (data.get("destination_path") or "").strip()
    suggested_filename = (data.get("suggested_filename") or "").strip()

    if not source_rel_path or (not destination_path and not suggested_filename):
        raise HTTPException(status_code=400, detail="缺少來源或目標路徑")

    source_full = (PATHS.root / source_rel_path).resolve()
    if not source_full.is_relative_to(PATHS.root.resolve()) or not source_full.exists():
        raise HTTPException(status_code=404, detail="來源成果檔案不存在或存取受限")

    client_host = request.client.host if request.client else ""
    is_local = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
    if not is_local:
        return {"status": "fallback", "message": "遠端連線無法開啟伺服器視窗，已自動切換為瀏覽器下載"}

    if destination_path:
        dest_full = Path(destination_path).resolve()
        try:
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_full, dest_full)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"檔案儲存失敗: {str(e)}")
        return {"status": "success", "saved_path": str(dest_full)}

    if os.name != "nt":
        return {"status": "fallback", "message": "目前作業系統環境不支援 Windows 原生另存對話框，已切換為瀏覽器下載"}

    dialog_script = PATHS.root / "src" / "scripts" / "native_dialog.py"
    if not dialog_script.exists():
        return {"status": "fallback", "message": "找不到原生對話框腳本，已切換為瀏覽器下載"}

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(dialog_script),
            str(source_full),
            suggested_filename,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PATHS.root),
        )
        stdout, _ = await proc.communicate()
        raw_out = stdout.decode("utf-8", errors="replace").strip()
        if raw_out:
            last_line = [ln.strip() for ln in raw_out.splitlines() if ln.strip()][-1]
            parsed = json.loads(last_line)
            if isinstance(parsed, dict) and parsed.get("status") in {"success", "cancelled"}:
                return parsed
        return {"status": "fallback", "message": "無法開啟原生另存視窗，已切換為瀏覽器下載"}
    except Exception:
        return {"status": "fallback", "message": "啟動原生另存視窗失敗，已切換為瀏覽器下載"}


@router.post("/api/open_file_folder")
async def open_file_folder(request: Request):
    """Open Windows File Explorer with specific file selected."""
    data = await request.json()
    raw_path = (data.get("path") or data.get("file_path") or "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="缺少檔案路徑")

    client_host = request.client.host if request.client else ""
    is_local = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
    if not is_local:
        return {"status": "fallback", "message": "遠端連線無法開啟伺服器資料夾，請改用瀏覽器下載。"}

    candidate = Path(raw_path)
    if candidate.is_absolute():
        full_path = candidate.resolve()
    else:
        full_path = (PATHS.root / raw_path).resolve()
        if not full_path.is_relative_to(PATHS.root.resolve()):
            raise HTTPException(status_code=404, detail="目標檔案存取受限")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="目標檔案不存在")

    try:
        norm_path = os.path.normpath(str(full_path))
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", norm_path])
            return {"status": "success", "message": "已在檔案總管中標記檔案"}
        return {"status": "fallback", "message": "非 Windows 環境無法開啟伺服器檔案總管，請改用瀏覽器下載。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"開啟檔案總管失敗: {str(e)}")
