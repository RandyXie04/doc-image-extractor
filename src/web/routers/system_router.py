# -*- coding: utf-8 -*-
"""
System, Hardware & Founder Tools FastAPI Router (`src/web/routers/system_router.py`)
====================================================================================
Modularized from `src/web/app.py` (P3-4 Risk 4 Remediation).
"""

from __future__ import annotations
import os
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from src.web.schemas import FounderRepairResponse

router = APIRouter(tags=["system"])


def _get_web_deps():
    import src.web.app as _web_app
    return _web_app.PATHS, _web_app.CFG, _web_app.save_upload_file_safely


def _cleanup_temp_files(*file_paths: str) -> None:
    """背景清理暫存檔，防止磁碟洩漏"""
    for p in file_paths:
        if p and os.path.exists(p):
            try:
                os.unlink(p)
            except Exception:
                pass


@router.get("/api/version")
async def get_version():
    from config import VERSION
    return {
        "app_version": VERSION.app_version,
        "model_version": VERSION.model_version,
    }


@router.post("/api/check_update")
async def check_update():
    from config import VERSION
    from src.scripts.updater_service import check_latest_release
    info = check_latest_release()
    if not info:
        return {"has_update": False, "status": "error", "msg": "無法連線至 GitHub 檢查更新。"}

    if info.get("status") == "no_releases":
        info["has_update"] = False
        info["msg"] = "目前線上尚未發布新版本，您使用的是最新本機版本。"
        return info

    if info.get("status") == "error":
        return info

    try:
        if info.get("latest_version"):
            remote_ver = [int(x) for x in info["latest_version"].split(".")]
            local_ver = [int(x) for x in VERSION.app_version.split(".")]
            has_update = remote_ver > local_ver
        else:
            has_update = False
    except Exception:
        has_update = False

    info["has_update"] = has_update
    return info


@router.post("/api/apply_update")
async def apply_update(request: Request):
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=403, detail="安全限制：系統更新僅允許伺服器本機操作")

    data = await request.json()
    download_url = data.get("download_url")
    if not download_url:
        return {"status": "error", "msg": "No download URL provided."}

    parsed = urllib.parse.urlparse(download_url)
    if parsed.scheme != "https" or parsed.netloc not in ("github.com", "objects.githubusercontent.com"):
        raise HTTPException(status_code=400, detail="不合法的更新下載來源網址")

    from src.scripts.updater_service import perform_update

    result = perform_update(download_url)
    if result.get("status") == "success":
        def delayed_exit():
            time.sleep(1)
            os._exit(0)
        threading.Thread(target=delayed_exit, daemon=True).start()
    return result


@router.get("/api/system_config")
async def get_system_config():
    """取得系統安全防護與無日誌配置資訊"""
    _, CFG, _ = _get_web_deps()
    return {
        "max_upload_size_mb": CFG.max_upload_size_mb,
        "max_template_size_mb": CFG.max_template_size_mb,
        "file_retention_hours": CFG.file_retention_hours,
        "enable_disk_logging": CFG.enable_disk_logging,
        "app_mode": CFG.app_mode,
    }


@router.get("/api/hardware_status")
async def get_hardware_status():
    _, CFG, _ = _get_web_deps()
    return CFG.get_hardware_profile()


@router.post("/api/founder/repair", response_model=FounderRepairResponse)
async def api_founder_repair(
    file: UploadFile = File(...),
) -> FounderRepairResponse:
    import asyncio
    from src.founder_tools.fix_founder_fonts import repair_docx_file, repair_pdf_file

    PATHS, CFG, save_upload_file_safely = _get_web_deps()
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供有效檔案名稱")

    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".pdf", ".docx"]:
        raise HTTPException(status_code=400, detail="不支援的檔案格式，請上傳 PDF 或 DOCX")

    task_id = str(uuid.uuid4())
    temp_input = PATHS.root / "scratch" / f"founder_repair_{task_id}{ext}"
    await save_upload_file_safely(file, temp_input, max_mb=CFG.max_upload_size_mb)
    created_temps = [str(temp_input)]

    output_dir = PATHS.root / "data" / "03_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".pdf":
            temp_out_txt = str(PATHS.root / "scratch" / f"founder_repair_{task_id}.txt")
            output_docx = output_dir / f"repaired_{Path(filename).stem}_{task_id[:8]}.docx"
            created_temps.append(temp_out_txt)

            await asyncio.to_thread(repair_pdf_file, str(temp_input), temp_out_txt, str(output_docx))
            _cleanup_temp_files(*created_temps)

            return FounderRepairResponse(
                success=True,
                source_path=f"data/03_output/{output_docx.name}",
                filename=output_docx.name,
            )

        output_docx = output_dir / f"repaired_{Path(filename).stem}_{task_id[:8]}.docx"
        await asyncio.to_thread(repair_docx_file, str(temp_input), str(output_docx))
        _cleanup_temp_files(*created_temps)

        return FounderRepairResponse(
            success=True,
            source_path=f"data/03_output/{output_docx.name}",
            filename=output_docx.name,
        )
    except Exception as e:
        _cleanup_temp_files(*created_temps)
        raise HTTPException(status_code=500, detail=f"修復過程發生異常: {str(e)}")


@router.post("/api/report_issue")
async def report_issue(request: Request):
    import platform

    data = await request.json()
    description = (data.get("description") or "").strip()[:2000]

    sys_info = f"OS: {platform.system()} {platform.release()}"
    body = f"**使用者回報:**\n{description}\n\n---\n**自動收集資訊:**\n```text\n{sys_info}\n```"

    repo = "RandyXie04/doc-image-extractor"
    encoded_title = urllib.parse.quote(f"[問題回報] {description[:30]}..." if description else "[問題回報] 請簡述問題")
    encoded_body = urllib.parse.quote(body)
    web_url = f"https://github.com/{repo}/issues/new?title={encoded_title}&body={encoded_body}"

    return {
        "status": "success",
        "url": web_url,
        "msg": "已生成 GitHub 官方回報頁面網址。",
    }

