from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import shutil
import uuid
import os
import io
import sys

import warnings
warnings.filterwarnings("ignore", message=".*The `fitz` API is deprecated.*")
import pymupdf as fitz
import numpy as np
from PIL import Image, ImageDraw
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.core_agent import PDFConversionAgent
from config import PATHS
from src.scripts.cleanup_scratch import cleanup_scratch

app = FastAPI(title="PDF AI 公式萃取站")

def cleanup_old_files():
    """自動清理 03_output 超過 24 小時之快取與產出檔案"""
    output_dir = PATHS.root / 'data' / '03_output'
    if not output_dir.exists():
        return
    import time
    now = time.time()
    for f in output_dir.glob('*'):
        if f.is_file() and (now - f.stat().st_mtime > 86400):
            try:
                f.unlink()
            except Exception:
                pass

@app.on_event("startup")
async def on_startup():
    # 首次啟動自動偵測並準備模型
    try:
        from src.scripts.model_manager import ensure_model_ready
        ensure_model_ready()
    except Exception as e:
        print(f"[Startup Warning] Model preparation failed: {e}")

    # 每月 1 號自動清空 scratch 暫存
    try:
        cleanup_scratch(force=False, log_fn=print)
    except Exception as e:
        print(f"[Startup Warning] Scratch cleanup failed: {e}")
    # 啟動時自動清理 24 小時過期輸出
    try:
        cleanup_old_files()
    except Exception as e:
        print(f"[Startup Warning] Old files cleanup failed: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory task tracker
tasks = {}
# Global OCR progress tracking
ocr_progress_dict = {}

@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...)):
    orig_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if orig_ext != ".pdf":
        raise HTTPException(status_code=400, detail="公式萃取與預覽僅支援 .pdf 格式檔案")
        
    file_id = f"{uuid.uuid4()}.pdf"
    file_path = PATHS.input_dir / file_id
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    total_pages = 1
    try:
        with fitz.open(file_path) as doc:
            total_pages = len(doc)
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=400, detail=f"無法解析此 PDF 檔案: {e}")

    orig_name = Path(file.filename).stem if file.filename else "已轉檔"
    return {"file_id": file_id, "total_pages": total_pages, "orig_name": orig_name}

@app.post("/api/upload_template")
async def upload_template(file: UploadFile = File(...)):
    if not file.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="僅支援上傳 .docx 格式的範本檔案")
    
    template_dir = Path("data/database_text/custom_templates")
    template_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = template_dir / "user_template.docx"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"status": "success", "message": f"範本 {file.filename} 上傳成功", "filename": file.filename}

@app.get("/api/get_current_template")
async def get_current_template():
    template_path = Path("data/database_text/custom_templates/user_template.docx")
    default_template_path = Path("data/database_text/template.docx")
    
    if template_path.exists():
        # Ideally we might want to store the original filename in a metadata file, 
        # but for simplicity we just return a static name or checking existence.
        return {"has_custom": True, "name": "user_template.docx"}
    elif default_template_path.exists():
        return {"has_custom": False, "name": "系統預設範本"}
    else:
        return {"has_custom": False, "name": "無可用範本"}

@app.get("/api/get_template_styles")
async def get_template_styles():
    import zipfile
    import xml.etree.ElementTree as ET
    
    template_path = Path("data/database_text/custom_templates/user_template.docx")
    if not template_path.exists():
        template_path = Path("data/database_text/template.docx")
        if not template_path.exists():
            return {"status": "error", "message": "無可用範本"}
            
    styles = []
    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(template_path, 'r') as z:
            if 'word/styles.xml' in z.namelist():
                tree = ET.fromstring(z.read('word/styles.xml'))
                for s in tree.findall(f"{W_NS}style"):
                    if s.get(f"{W_NS}type") == "paragraph":
                        name_el = s.find(f"{W_NS}name")
                        if name_el is not None:
                            name_val = name_el.get(f"{W_NS}val")
                            if name_val:
                                styles.append(name_val)
    except Exception as e:
        return {"status": "error", "message": f"解析樣式失敗: {e}"}
        
    return {"status": "success", "styles": styles}

@app.get("/api/version")
async def get_version():
    from config import VERSION
    return {
        "app_version": VERSION.app_version,
        "model_version": VERSION.model_version
    }

@app.post("/api/check_update")
async def check_update():
    from config import VERSION
    from src.scripts.updater_service import check_latest_release
    info = check_latest_release()
    if not info:
        return {"has_update": False, "status": "error", "msg": "無法連線至 GitHub 檢查更新。"}
    
    if info.get('status') == 'no_releases':
        info['has_update'] = False
        info['msg'] = "目前線上尚未發布新版本，您使用的是最新本機版本。"
        return info

    if info.get('status') == 'error':
        return info
    
    try:
        if info.get('latest_version'):
            remote_ver = [int(x) for x in info['latest_version'].split('.')]
            local_ver = [int(x) for x in VERSION.app_version.split('.')]
            has_update = remote_ver > local_ver
        else:
            has_update = False
    except Exception:
        has_update = False
            
    info['has_update'] = has_update
    return info

@app.post("/api/apply_update")
async def apply_update(request: Request):
    data = await request.json()
    download_url = data.get('download_url')
    if not download_url:
        return {"status": "error", "msg": "No download URL provided."}
        
    from src.scripts.updater_service import perform_update
    import threading
    import time
    
    result = perform_update(download_url)
    if result.get('status') == 'success':
        def delayed_exit():
            time.sleep(1)
            os._exit(0)
        threading.Thread(target=delayed_exit, daemon=True).start()
    return result

@app.get("/api/render_preview/{file_id}")
async def render_preview(file_id: str, page: int = 1, header: float = 0.1, footer: float = 0.1, left: float = 0.0, right: float = 0.0):
    """回傳帶有裁切輔助線（上下紅藍、左右綠）的單頁 PDF 預覽圖"""
    file_path = PATHS.input_dir / file_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        with fitz.open(file_path) as doc:
            page_idx = max(0, min(page - 1, len(doc) - 1))
            page_obj = doc[page_idx]
            
            # 渲染成圖片
            pix = page_obj.get_pixmap(dpi=72)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # 繪製輔助線
            draw = ImageDraw.Draw(img)
            w, h = img.size
            y_header = int(h * header)
            y_footer = int(h * (1.0 - footer))
            x_left = int(w * left)
            x_right = int(w * (1.0 - right))
            
            # 上下水平輔助線 (頂部紅、底部藍)
            draw.line([(0, y_header), (w, y_header)], fill="red", width=2)
            draw.line([(0, y_footer), (w, y_footer)], fill="blue", width=2)

            # 左右垂直輔助線 (綠色)
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

def process_pdf(task_id: str, file_path: str, convert_word: bool, extract_formulas: bool, start_page: int, end_page: int, header_ratio: float, footer_ratio: float, left_ratio: float = 0.0, right_ratio: float = 0.0, extract_inline: bool = False, embed_formulas_in_word: bool = True):
    try:
        tasks[task_id]["status"] = "processing"
        tasks[task_id]["progress"] = 5.0
        
        def progress_cb(current, total, msg):
            pct = 5.0 + (current / total) * 90.0
            tasks[task_id]["progress"] = pct
            tasks[task_id]["message"] = msg
            tasks[task_id]["log"] += f"[{current}/{total}] {msg}\n"
            
        def log_fn(msg):
            tasks[task_id]["log"] += f"{msg}\n"
            
        log_fn(f"[DEBUG] 轉檔配置: convert_word={convert_word}, extract_formulas={extract_formulas}, extract_inline={extract_inline}, embed_formulas_in_word={embed_formulas_in_word}")

        agent = PDFConversionAgent(
            input_pdf=file_path, 
            header_ratio=header_ratio, 
            footer_ratio=footer_ratio,
            left_ratio=left_ratio,
            right_ratio=right_ratio,
            extract_inline=extract_inline,
            embed_formulas_in_word=embed_formulas_in_word
        )
        
        pipeline_res = agent.execute_pipeline(
            convert_word=convert_word,
            extract_formulas=extract_formulas,
            start_page_idx=start_page,
            end_page_idx=end_page if end_page > 0 else None,
            log_fn=log_fn,
            progress_callback=progress_cb
        )
        
        if pipeline_res and pipeline_res.get("delivery_folder"):
            tasks[task_id]["word_file"] = pipeline_res.get("word_path")
            tasks[task_id]["zip_file"] = pipeline_res.get("zip_path")
            tasks[task_id]["result_file"] = pipeline_res.get("zip_path") or pipeline_res.get("word_path")
            tasks[task_id]["progress"] = 100.0
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["message"] = "處理完成"
        else:
            raise Exception("未能產生有效輸出成果")
            
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["message"] = f"錯誤: {str(e)}"
        tasks[task_id]["log"] += f"\n發生異常：{str(e)}\n"

@app.post("/api/process")
async def start_process(
    background_tasks: BackgroundTasks,
    file_id: str = Form(...),
    convert_word: bool = Form(True),
    extract_formulas: bool = Form(True),
    start_page: int = Form(0),
    end_page: int = Form(0),
    header_ratio: float = Form(0.1),
    footer_ratio: float = Form(0.1),
    left_ratio: float = Form(0.0),
    right_ratio: float = Form(0.0),
    extract_inline: bool = Form(False),
    embed_formulas_in_word: bool = Form(True),
    orig_name: str = Form("")
):
    file_path = PATHS.input_dir / file_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "排隊中...",
        "log": "任務已加入佇列...\n",
        "result_file": None,
        "word_file": None,
        "zip_file": None,
        "orig_name": orig_name or "已轉檔"
    }
    
    background_tasks.add_task(
        process_pdf, 
        task_id, 
        str(file_path), 
        convert_word, 
        extract_formulas, 
        start_page, 
        end_page, 
        header_ratio, 
        footer_ratio,
        left_ratio,
        right_ratio,
        extract_inline,
        embed_formulas_in_word
    )
    return {"task_id": task_id}

@app.get("/api/app_mode")
async def get_app_mode():
    """取得當前運行模式：editor (出版社編輯) 或 dev (內部工程師)"""
    from config import CFG
    return {"mode": CFG.app_mode}

@app.post("/api/set_app_mode")
async def set_app_mode(request: Request):
    """動態切換運行模式 (免重啟)"""
    data = await request.json()
    new_mode = data.get("mode", "editor").lower()
    if new_mode not in ["editor", "dev"]:
        raise HTTPException(status_code=400, detail="模式必須為 'editor' 或 'dev'")
    import config.settings
    object.__setattr__(config.settings.CFG, "app_mode", new_mode)
    return {"status": "success", "mode": new_mode}



# Mount static files
static_dir = Path(__file__).parent / "static"
if not static_dir.exists() and getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _candidate = Path(sys._MEIPASS) / "src" / "web" / "static"
    if _candidate.exists():
        static_dir = _candidate
    else:
        _candidate2 = Path(sys._MEIPASS) / "static"
        if _candidate2.exists():
            static_dir = _candidate2

os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    raise HTTPException(status_code=404, detail="Index page not found")

@app.get("/{page}.html", response_class=HTMLResponse)
async def read_page(page: str):
    file_path = static_dir / f"{page}.html"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    raise HTTPException(status_code=404, detail="Page not found")

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    if task_id not in tasks:
        return {"status": "not_found"}
    return tasks[task_id]

@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    """向下相容通用下載端點"""
    if task_id in tasks and tasks[task_id].get("result_file"):
        path = tasks[task_id]["result_file"]
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if path.endswith(".docx") else "application/zip"
        return FileResponse(path, media_type=media_type, filename=os.path.basename(path))
    return {"error": "File not found or task not completed"}

@app.get("/api/hardware_status")
async def get_hardware_status():
    from config import CFG
    profile = CFG.get_hardware_profile()
    return profile

@app.get("/api/download/{task_id}/word")
async def download_word(task_id: str):
    """專用 Word 文件下載端點"""
    if task_id in tasks and tasks[task_id].get("word_file"):
        path = tasks[task_id]["word_file"]
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=os.path.basename(path)
        )
    return {"error": "Word file not available for this task"}

@app.get("/api/download/{task_id}/formulas")
async def download_formulas(task_id: str):
    """專用公式圖檔包下載端點"""
    if task_id in tasks and tasks[task_id].get("zip_file"):
        path = tasks[task_id]["zip_file"]
        return FileResponse(
            path,
            media_type="application/zip",
            filename=os.path.basename(path)
        )
    return {"error": "Formula ZIP not available for this task"}

# =========================================================================
# 文件圖片無損提取 API (DOCX / PDF)
# =========================================================================
extracted_image_tasks = {}

@app.post("/api/extract_images")
async def api_extract_images(
    file: UploadFile = File(...),
    to_grayscale: bool = Form(False)
):
    from src.scripts.extract_images import process_document_images
    import asyncio

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
    with open(input_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        count, zip_path = await asyncio.to_thread(
            process_document_images,
            file_path=str(input_file_path),
            output_zip_path=str(output_zip_path),
            temp_dir=str(extracted_folder),
            to_grayscale=to_grayscale
        )

        extracted_image_tasks[task_id] = {
            "zip_path": str(zip_path),
            "filename": output_zip_name,
            "count": count
        }

        return {
            "success": True,
            "count": count,
            "download_url": f"/api/download_extracted_images/{task_id}",
            "filename": output_zip_name,
            "source_path": f"data/03_output/{output_zip_name}",
            "message": f"成功提取 {count} 張圖片！" if count > 0 else "未在此文件中偵測到任何內嵌圖片。"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"圖片提取失敗: {str(e)}")
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

@app.get("/api/download_extracted_images/{task_id}")
async def download_extracted_images(task_id: str):
    if task_id in extracted_image_tasks:
        info = extracted_image_tasks[task_id]
        zip_path = info["zip_path"]
        if os.path.exists(zip_path):
            return FileResponse(
                zip_path,
                media_type="application/zip",
                filename=info["filename"]
            )
    raise HTTPException(status_code=404, detail="找不到提取的壓縮檔案或任務不存在")


@app.post("/api/open_folder/{task_id}")
async def open_folder(task_id: str):
    """在 Windows 檔案總管中開啟成果所在資料夾並選取檔案"""
    if task_id in tasks:
        target = tasks[task_id].get("word_file") or tasks[task_id].get("zip_file") or tasks[task_id].get("result_file")
        if target and os.path.exists(target):
            import subprocess
            subprocess.Popen(f'explorer /select,"{os.path.abspath(target)}"')
            return {"status": "success"}
    raise HTTPException(status_code=404, detail="成果檔案不存在或尚未生成")

@app.post("/api/save_word_dialog/{task_id}")
async def save_word_dialog(task_id: str):
    """
    [出版社編輯專用] 彈出 Windows 原生檔案總管『另存新檔』視窗，
    讓編輯指定任意儲存路徑 (如桌面或工作資料夾)，並自動複製檔案。
    採用非同步獨立進程以確保不阻塞 Event Loop，並強制視窗前置獲得焦點。
    """
    if task_id not in tasks or not tasks[task_id].get("word_file"):
        raise HTTPException(status_code=404, detail="找不到轉檔成果")
        
    src_word = tasks[task_id]["word_file"]
    if not os.path.exists(src_word):
        raise HTTPException(status_code=404, detail="生成的 Word 檔案不存在")

    orig_name = tasks[task_id].get("orig_name", "已轉檔書籍")
    default_filename = f"{orig_name}_已轉檔.docx"

    cmd = [
        sys.executable,
        str(PATHS.root / "src" / "scripts" / "native_dialog.py"),
        str(src_word),
        default_filename
    ]
    try:
        import asyncio
        import json
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PATHS.root)
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        output_str = stdout.decode("utf-8", errors="replace").strip()
        if output_str:
            try:
                res_data = json.loads(output_str)
                if res_data.get("status") == "success":
                    tasks[task_id]["saved_user_path"] = res_data["saved_path"]
                    return {
                        "status": "success",
                        "saved_path": res_data["saved_path"],
                        "filename": os.path.basename(res_data["saved_path"]),
                        "message": f"成功儲存至：{res_data['saved_path']}"
                    }
                elif res_data.get("status") == "cancelled":
                    return {"status": "cancelled", "message": "已取消儲存"}
            except Exception:
                pass
        return {"status": "cancelled", "message": "已取消儲存"}
    except Exception as e:
        print(f"[SaveDialog] 原生檔案對話框失敗: {e}")
        return {"status": "fallback", "message": "請使用瀏覽器直接下載"}

@app.post("/api/open_saved_folder/{task_id}")
async def open_saved_folder(task_id: str):
    """在 Windows 檔案總管中開啟編輯剛才指定另存的檔案目錄並選取檔案"""
    if task_id in tasks and tasks[task_id].get("saved_user_path"):
        target = tasks[task_id]["saved_user_path"]
        if os.path.exists(target):
            import subprocess
            subprocess.Popen(f'explorer /select,"{os.path.abspath(target)}"')
            return {"status": "success"}
    return await open_folder(task_id)


# =========================================================================
# Founder Tools API (方正排版修復)
# =========================================================================
def _cleanup_temp_files(*file_paths):
    """背景清理暫存檔，防止磁碟洩漏"""
    for p in file_paths:
        if p and os.path.exists(p):
            try:
                os.unlink(p)
            except Exception:
                pass

@app.post("/api/founder/repair")
async def api_founder_repair(
    file: UploadFile = File(...)
):
    import os
    import shutil
    import asyncio
    import uuid
    from src.founder_tools.fix_founder_fonts import repair_pdf_file, repair_docx_file
    from config import PATHS
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".docx"]:
        raise HTTPException(status_code=400, detail="不支援的檔案格式，請上傳 PDF 或 DOCX")

    task_id = str(uuid.uuid4())
    temp_input = PATHS.root / "scratch" / f"founder_repair_{task_id}{ext}"
    
    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    created_temps = [str(temp_input)]
    
    output_dir = PATHS.root / "data" / "03_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".pdf":
            temp_out_txt = str(PATHS.root / "scratch" / f"founder_repair_{task_id}.txt")
            output_docx = output_dir / f"repaired_{Path(file.filename).stem}.docx"
            created_temps.append(temp_out_txt)
            
            await asyncio.to_thread(repair_pdf_file, str(temp_input), temp_out_txt, str(output_docx))
            _cleanup_temp_files(*created_temps)
            
            return {
                "success": True,
                "source_path": f"data/03_output/{output_docx.name}",
                "filename": output_docx.name
            }
            
        elif ext == ".docx":
            output_docx = output_dir / f"repaired_{Path(file.filename).name}"
            
            await asyncio.to_thread(repair_docx_file, str(temp_input), str(output_docx))
            _cleanup_temp_files(*created_temps)
            
            return {
                "success": True,
                "source_path": f"data/03_output/{output_docx.name}",
                "filename": output_docx.name
            }
            
    except Exception as e:
        _cleanup_temp_files(*created_temps)
        raise HTTPException(status_code=500, detail=f"修復過程發生異常: {str(e)}")


@app.post("/api/report_issue")
async def report_issue(request: Request):
    import platform
    import urllib.parse
    
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
        "msg": "已生成 GitHub 官方回報頁面網址。"
    }





@app.get("/api/ocr_progress/{filename_stem}")
async def get_ocr_progress(filename_stem: str):
    progress = ocr_progress_dict.get(filename_stem, {"progress": 0, "message": "Waiting...", "status": "processing"})
    return progress

@app.post("/api/upload_and_run_ocr")
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
    right_ratio: float = Form(0.0)
):
    import sys
    import shutil
    import os
    from config import PATHS
    
    pdf_dir = PATHS.root / 'data' / 'database_text'
    pdf_dir.mkdir(parents=True, exist_ok=True)
    
    # Support pre-uploaded file_id or direct upload
    if file_id and (PATHS.input_dir / file_id).exists():
        raw_pdf_path = PATHS.input_dir / file_id
        filename_stem = filename_orig or Path(file_id).stem
    elif file and file.filename:
        clean_filename = Path(file.filename).name
        ext = os.path.splitext(clean_filename)[1].lower()
        if ext != ".pdf":
            raise HTTPException(status_code=400, detail="僅支援 PDF 檔案格式")
        raw_pdf_path = pdf_dir / clean_filename
        with open(raw_pdf_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        filename_stem = Path(clean_filename).stem
    else:
        raise HTTPException(status_code=400, detail="請提供 PDF 檔案或檔案代碼")

    # WYSIWYG pre-crop using fitz
    input_pdf_path = raw_pdf_path
    if header_ratio > 0 or footer_ratio > 0 or left_ratio > 0 or right_ratio > 0:
        cropped_pdf_path = pdf_dir / f"cropped_{filename_stem}.pdf"
        try:
            with fitz.open(raw_pdf_path) as doc:
                for page in doc:
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
            print(f"[Warning] PDF pre-crop failed: {crop_err}")
            input_pdf_path = raw_pdf_path

    ocr_progress_dict[filename_stem] = {"progress": 0, "message": "正在初始化任務...", "status": "processing"}

    async def run_scripts_async(pdf_path_str, stem, style_map_json, eng):
        import asyncio
        import json as _json
        try:
            output_dir = PATHS.root / 'data' / '03_output'
            backup_dir = output_dir / 'backup_originals'
            output_dir.mkdir(parents=True, exist_ok=True)
            
            md_file = output_dir / f"{stem}.md"
            docx_file = output_dir / f"{stem}.docx"
            
            for f_path in [md_file, docx_file]:
                if f_path.exists():
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_path = backup_dir / f_path.name
                    try: shutil.move(str(f_path), str(backup_path))
                    except: pass

            cmd = [
                sys.executable, str(PATHS.root / "src" / "scripts" / "pdf_engine_dispatcher.py"), 
                "--file", pdf_path_str,
                "--output_dir", str(output_dir),  # absolute path
                "--output_stem", stem,
                "--engine", eng
            ]
            if style_map_json:
                cmd.extend(["--style_mapping", style_map_json])
                
            # Use asyncio subprocess to avoid blocking the event loop
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(PATHS.root)
            )
            
            async for raw_line in proc.stdout:
                try:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                except Exception:
                    line = ""
                if line:
                    if line.startswith("{") and "progress" in line:
                        try:
                            data = _json.loads(line)
                            ocr_progress_dict[stem]["progress"] = data.get("progress", ocr_progress_dict[stem]["progress"])
                            ocr_progress_dict[stem]["message"] = data.get("message", line)
                        except Exception:
                            pass
                    else:
                        ocr_progress_dict[stem]["message"] = line[:120]
            
            await proc.wait()
            
            if proc.returncode != 0:
                ocr_progress_dict[stem]["status"] = "failed"
                ocr_progress_dict[stem]["message"] = f"轉檔程序執行失敗 (代碼: {proc.returncode})"
                return

            ocr_progress_dict[stem]["progress"] = 92
            ocr_progress_dict[stem]["message"] = "正在套用樣式並產生 Word (.docx) 文件..."
            
            if md_file.exists():
                md_proc = await asyncio.create_subprocess_exec(
                    sys.executable, str(PATHS.root / "src" / "scripts" / "md_to_docx.py"),
                    "--files", str(md_file),
                    cwd=str(PATHS.root),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await md_proc.wait()
                
            ocr_progress_dict[stem]["progress"] = 100
            ocr_progress_dict[stem]["message"] = "轉檔完成！"
            ocr_progress_dict[stem]["status"] = "completed"
        except Exception as err:
            ocr_progress_dict[stem]["status"] = "failed"
            ocr_progress_dict[stem]["message"] = f"處理過程異常: {str(err)}"

    import asyncio
    asyncio.ensure_future(run_scripts_async(str(input_pdf_path), filename_stem, style_mapping, engine))
    return {"message": "OCR 管道已成功啟動", "filename_stem": filename_stem}


@app.get("/api/download_ocr_result/{filename_stem}/{ext}")
async def download_ocr_result(filename_stem: str, ext: str):
    from config import PATHS
    if ext not in ["docx", "md"]:
        raise HTTPException(status_code=400, detail="僅支援下載 docx 或 md")
    output_dir = PATHS.root / 'data' / '03_output'
    file_path = output_dir / f"{filename_stem}.{ext}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="檔案尚未生成或不存在")
    return FileResponse(file_path, filename=f"{filename_stem}.{ext}")

from pydantic import BaseModel
class MarkdownUpdate(BaseModel):
    content: str

@app.get("/api/get_markdown/{filename_stem}")
async def get_markdown(filename_stem: str):
    from config import PATHS
    md_file = PATHS.root / 'data' / '03_output' / f"{filename_stem}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Markdown file not found")
    with open(md_file, "r", encoding="utf-8") as f:
        return {"content": f.read()}

@app.post("/api/update_and_rebuild_docx/{filename_stem}")
async def update_and_rebuild_docx(filename_stem: str, data: MarkdownUpdate):
    import subprocess
    import sys
    from config import PATHS
    
    md_file = PATHS.root / 'data' / '03_output' / f"{filename_stem}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Markdown file not found")
        
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(data.content)
        
    # Re-run md_to_docx.py
    cmd = [sys.executable, str(PATHS.root / "src" / "scripts" / "md_to_docx.py"), "--files", str(md_file)]
    subprocess.run(cmd, cwd=str(PATHS.root))
    
    return {"status": "success", "message": "已成功更新大綱並重新生成 Word 文件！"}

class NativeSaveRequest(BaseModel):
    source_path: str
    suggested_filename: str = ""

@app.post("/api/native_save_file")
async def api_native_save_file(req: NativeSaveRequest):
    """
    [出版社編輯專用] 呼叫 Windows 原生檔案總管『另存新檔』視窗，
    具備嚴格路徑白名單校驗 (Path Traversal 防禦 - NIST PR.DS / ISO 27001 A.8.28)
    與非同步子進程防阻塞 (NIST PR.IP)。
    """
    import asyncio
    import json
    import sys
    from config import PATHS
    
    # 1. 嚴格路徑校驗 (Path Traversal 防禦)
    allowed_dirs = [
        (PATHS.root / "data" / "03_output").resolve(),
        (PATHS.root / "data" / "02_intermediate").resolve(),
        PATHS.data_dir.resolve()
    ]
    
    target_path = Path(req.source_path)
    if not target_path.is_absolute():
        target_path = (PATHS.root / req.source_path).resolve()
    else:
        target_path = target_path.resolve()
        
    is_safe = any(
        str(target_path).startswith(str(d)) for d in allowed_dirs
    )
    if not is_safe:
        raise HTTPException(status_code=403, detail="存取受限：路徑超出允許之專案輸出目錄")
        
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="指定之輸出檔案不存在")
        
    suggested_filename = req.suggested_filename or target_path.name
    
    # 2. 非同步子進程執行原生對話框 (非阻塞 Event Loop)
    cmd = [
        sys.executable,
        str(PATHS.root / "src" / "scripts" / "native_dialog.py"),
        str(target_path),
        suggested_filename
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PATHS.root)
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        output_str = stdout.decode("utf-8", errors="replace").strip()
        
        if output_str:
            try:
                res_data = json.loads(output_str)
                return res_data
            except Exception:
                pass
                
        return {"status": "cancelled", "message": "對話框已關閉或未選取檔案"}
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"status": "fallback", "message": "操作逾時，請改用瀏覽器直接下載"}
    except Exception as e:
        return {"status": "error", "message": f"原生另存失敗: {str(e)}"}

class OpenFileFolderRequest(BaseModel):
    file_path: str

@app.post("/api/open_file_folder")
async def api_open_file_folder(req: OpenFileFolderRequest):
    """在 Windows 檔案總管中定位並選取已儲存之檔案"""
    import subprocess
    target = Path(req.file_path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="目標檔案不存在")
    subprocess.Popen(f'explorer /select,"{str(target)}"')
    return {"status": "success"}


