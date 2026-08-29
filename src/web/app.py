from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import shutil
import uuid
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.core_agent import PDFConversionAgent
from config import PATHS

app = FastAPI(title="PDF Formula Extractor Web")

# Mount static files
static_dir = Path(__file__).parent / "static"
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Simple in-memory task tracker
tasks = {}

def process_pdf(task_id: str, input_pdf: str, convert_word: bool, extract_formulas: bool, start_page: int, end_page: int):
    tasks[task_id]["status"] = "processing"
    tasks[task_id]["progress"] = 0.0
    tasks[task_id]["log"] = ""
    
    def log_callback(msg):
        tasks[task_id]["log"] += str(msg) + "\n"
        print(msg)
        
    def progress_callback(current, total, msg):
        tasks[task_id]["progress"] = (current / total) * 100
        tasks[task_id]["message"] = msg

    try:
        agent = PDFConversionAgent(input_pdf=input_pdf)
        delivery_folder = agent.execute_pipeline(
            convert_word=convert_word,
            extract_formulas=extract_formulas,
            start_page_idx=start_page,
            end_page_idx=end_page if end_page > 0 else None,
            log_fn=log_callback,
            progress_callback=progress_callback
        )
        
        if delivery_folder:
            # zip the delivery folder to a single file for download
            zip_out = str(PATHS.root / "data" / "03_output" / f"{task_id}.zip")
            shutil.make_archive(zip_out.replace(".zip", ""), 'zip', delivery_folder)
            tasks[task_id]["result_file"] = zip_out
            tasks[task_id]["status"] = "completed"
        else:
            tasks[task_id]["status"] = "failed"
    except Exception as e:
        tasks[task_id]["log"] += f"\nError: {e}"
        tasks[task_id]["status"] = "failed"
        print(f"Error processing {task_id}: {e}")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open(static_dir / "index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    convert_word: bool = Form(True),
    extract_formulas: bool = Form(True),
    start_page: int = Form(0),
    end_page: int = Form(0)
):
    task_id = str(uuid.uuid4())
    
    # Save uploaded file
    input_dir = PATHS.input_dir
    input_dir.mkdir(parents=True, exist_ok=True)
    file_path = input_dir / f"{task_id}_{file.filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    tasks[task_id] = {"status": "pending", "progress": 0.0, "message": "等待處理中...", "filename": file.filename}
    
    # Start background task
    background_tasks.add_task(process_pdf, task_id, str(file_path), convert_word, extract_formulas, start_page, end_page)
    
    return {"task_id": task_id}

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
