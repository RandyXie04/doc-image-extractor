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

@app.on_event("startup")
async def on_startup():
    # 每月 1 號自動清空 scratch 暫存
    try:
        cleanup_scratch(force=False, log_fn=print)
    except Exception as e:
        print(f"[Startup Warning] Scratch cleanup failed: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory task tracker
tasks = {}

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

    return {"file_id": file_id, "total_pages": total_pages}

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
        return {"has_update": False, "msg": "無法連線至 GitHub 檢查更新。"}
    
    try:
        remote_ver = [int(x) for x in info['latest_version'].split('.')]
        local_ver = [int(x) for x in VERSION.app_version.split('.')]
        has_update = remote_ver > local_ver
    except:
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
    embed_formulas_in_word: bool = Form(True)
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
        "zip_file": None
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
        count, zip_path = process_document_images(
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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    import tempfile
    import os
    import shutil
    from fastapi.responses import FileResponse
    from src.founder_tools.fix_founder_fonts import repair_pdf_file, repair_docx_file
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".docx"]:
        raise HTTPException(status_code=400, detail="不支援的檔案格式，請上傳 PDF 或 DOCX")

    fd, temp_input = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    
    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    created_temps = [temp_input]

    try:
        if ext == ".pdf":
            fd_txt, temp_out_txt = tempfile.mkstemp(suffix=".txt")
            os.close(fd_txt)
            fd_docx, temp_out_docx = tempfile.mkstemp(suffix=".docx")
            os.close(fd_docx)
            created_temps.extend([temp_out_txt, temp_out_docx])
            
            repair_pdf_file(temp_input, temp_out_txt, temp_out_docx)
            # 將中間 txt 與輸入 input 清理，輸出 docx 待傳輸完後清理
            background_tasks.add_task(_cleanup_temp_files, temp_input, temp_out_txt, temp_out_docx)
            return FileResponse(
                temp_out_docx, 
                filename=f"repaired_{file.filename}.docx", 
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            
        elif ext == ".docx":
            fd_docx, temp_out_docx = tempfile.mkstemp(suffix=".docx")
            os.close(fd_docx)
            created_temps.append(temp_out_docx)
            
            repair_docx_file(temp_input, temp_out_docx)
            background_tasks.add_task(_cleanup_temp_files, temp_input, temp_out_docx)
            return FileResponse(
                temp_out_docx, 
                filename=f"repaired_{file.filename}", 
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            
    except Exception as e:
        _cleanup_temp_files(*created_temps)
        raise HTTPException(status_code=500, detail=f"修復過程發生異常: {str(e)}")


@app.post("/api/report_issue")
async def report_issue(request: Request):
    import subprocess
    import platform
    
    data = await request.json()
    description = data.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="內容不可為空")
        
    sys_info = f"OS: {platform.system()} {platform.release()}"
    body = f"**使用者回報:**\n{description}\n\n---\n**自動收集資訊:**\n```text\n{sys_info}\n```"
    
    try:
        cmd = [
            "gh", "issue", "create", 
            "--title", f"內部回報: {description[:30]}...", 
            "--body", body,
            "--label", "user-feedback"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if result.returncode != 0 and "not found" in result.stderr:
            # Fallback without label
            cmd_fallback = [
                "gh", "issue", "create", 
                "--title", f"內部回報: {description[:30]}...", 
                "--body", body
            ]
            result = subprocess.run(cmd_fallback, capture_output=True, text=True, check=True, encoding='utf-8')
        elif result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
        
        issue_url = result.stdout.strip()
        return {"success": True, "url": issue_url, "message": "回報成功！感謝您的反饋。"}
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise HTTPException(status_code=500, detail=f"提交失敗: {error_msg}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="系統未安裝 GitHub CLI (gh)，或未加入 PATH。")



@app.post("/api/upload_and_run_ocr")
async def upload_and_run_ocr(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    import subprocess
    import sys
    import shutil
    import os
    import tempfile
    from config import PATHS
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".pdf":
        raise HTTPException(status_code=400, detail="僅支援 PDF 檔案格式")

    # Save to database_text folder
    pdf_dir = PATHS.root / 'data' / 'database_text'
    pdf_dir.mkdir(parents=True, exist_ok=True)
    
    temp_pdf_path = pdf_dir / file.filename
    with open(temp_pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    def run_scripts(pdf_path_str, filename_stem):
        output_dir = PATHS.root / 'data' / '03_output'
        backup_dir = output_dir / 'backup_originals'
        
        # 1. 執行前狀態檢查／清理選項
        md_file = output_dir / f"{filename_stem}.md"
        docx_file = output_dir / f"{filename_stem}.docx"
        
        for f in [md_file, docx_file]:
            if f.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backup_dir / f.name
                print(f"[Cleanup] Backing up existing output {f.name} to {backup_dir}")
                try:
                    shutil.move(str(f), str(backup_path))
                except Exception as e:
                    print(f"Error moving {f.name}: {e}")

        # 2. Run OCR and MD generation specifically for this file
        subprocess.run([sys.executable, str(PATHS.root / "src" / "scripts" / "process_ocr.py"), "--file", pdf_path_str], cwd=str(PATHS.root))
        
        # 3. 收集本次成功生成的 .md 清單傳遞給 md_to_docx.py
        new_md_files = []
        if md_file.exists():
            new_md_files.append(str(md_file))
                
        # Run MD to DOCX conversion passing specific files
        if new_md_files:
            print(f"Passing {len(new_md_files)} files to md_to_docx.py: {new_md_files}")
            subprocess.run([sys.executable, str(PATHS.root / "src" / "scripts" / "md_to_docx.py"), "--files"] + new_md_files, cwd=str(PATHS.root))
        else:
            print("No new markdown files were generated.")

    # Execute script in background task
    background_tasks.add_task(run_scripts, str(temp_pdf_path), Path(file.filename).stem)
    return {"message": "OCR 管線已成功啟動", "filename_stem": Path(file.filename).stem}

@app.get("/api/download_ocr_result/{filename_stem}/{ext}")
async def download_ocr_result(filename_stem: str, ext: str):
    from config import PATHS
    import os
    from fastapi.responses import FileResponse
    
    if ext not in ["docx", "md"]:
        raise HTTPException(status_code=400, detail="僅支援下載 docx 或 md")
        
    output_dir = PATHS.root / 'data' / '03_output'
    file_path = output_dir / f"{filename_stem}.{ext}"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"檔案尚未產生或處理失敗: {filename_stem}.{ext}")
        
    return FileResponse(
        file_path,
        filename=f"{filename_stem}.{ext}"
    )

