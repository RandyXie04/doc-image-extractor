from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import shutil
import uuid
import os
import io
import sys
import fitz
import numpy as np
from PIL import Image, ImageDraw
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.core_agent import PDFConversionAgent
from config import PATHS

app = FastAPI(title="PDF AI 公式萃取站")

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
    """接收上傳的 PDF 檔案並回傳 file_id"""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支援 PDF 檔案")
        
    file_id = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    input_dir = PATHS.input_dir
    input_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = input_dir / file_id
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"file_id": file_id}

@app.get("/api/render_preview/{file_id}")
async def render_preview(file_id: str, page: int = 1, header: float = 0.1, footer: float = 0.1):
    """回傳帶有裁切輔助線的單頁 PDF 預覽圖"""
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
            
            # 畫紅線
            draw = ImageDraw.Draw(img)
            w, h = img.size
            y_header = int(h * header)
            y_footer = int(h * (1 - footer))
            
            draw.line([(0, y_header), (w, y_header)], fill="red", width=2)
            draw.line([(0, y_footer), (w, y_footer)], fill="blue", width=2)
            
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            buf.seek(0)
            
            return StreamingResponse(buf, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_pdf(task_id: str, file_path: str, convert_word: bool, extract_formulas: bool, start_page: int, end_page: int, header_ratio: float, footer_ratio: float):
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

        agent = PDFConversionAgent(
            input_pdf=file_path, 
            header_ratio=header_ratio, 
            footer_ratio=footer_ratio
        )
        
        delivery_folder = agent.execute_pipeline(
            convert_word=convert_word,
            extract_formulas=extract_formulas,
            start_page_idx=start_page,
            end_page_idx=end_page if end_page > 0 else None,
            log_fn=log_fn,
            progress_callback=progress_cb
        )
        
        if delivery_folder:
            zip_out = str(PATHS.root / "data" / "03_output" / f"{task_id}.zip")
            shutil.make_archive(zip_out.replace(".zip", ""), 'zip', delivery_folder)
            tasks[task_id]["result_file"] = zip_out
            tasks[task_id]["progress"] = 100.0
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["message"] = "處理完成"
        else:
            raise Exception("未能產生輸出資料夾")
            
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["message"] = f"錯誤: {str(e)}"
        tasks[task_id]["log"] += f"\n發生崩潰：{str(e)}\n"

@app.post("/api/process")
async def start_process(
    background_tasks: BackgroundTasks,
    file_id: str = Form(...),
    convert_word: bool = Form(True),
    extract_formulas: bool = Form(True),
    start_page: int = Form(0),
    end_page: int = Form(0),
    header_ratio: float = Form(0.1),
    footer_ratio: float = Form(0.1)
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
        "result_file": None
    }
    
    background_tasks.add_task(process_pdf, task_id, str(file_path), convert_word, extract_formulas, start_page, end_page, header_ratio, footer_ratio)
    return {"task_id": task_id}

# Mount static files
static_dir = Path(__file__).parent / "static"
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open(static_dir / "index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    if task_id not in tasks:
        return {"status": "not_found"}
    return tasks[task_id]

@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    if task_id in tasks and tasks[task_id].get("result_file"):
        return FileResponse(
            tasks[task_id]["result_file"], 
            media_type="application/zip",
            filename=f"extracted_result_{tasks[task_id]['filename']}.zip"
        )
    return {"error": "File not found or task not completed"}
