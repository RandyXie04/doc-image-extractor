import os
import sys
import urllib.request
import json
import urllib.error
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import PATHS

GITHUB_REPO = 'RandyXie04/doc-image-extractor'
DEFAULT_MODEL_NAME = "yolo_v8_ft.onnx"
DEFAULT_PT_NAME = "yolo_v8_ft.pt"

def _get_exact_model_path(model_name: str) -> Path | None:
    """Find the exact model file without fallback extensions."""
    search_paths = [
        PATHS.bundle_root / "models" / model_name,
        Path.cwd() / "models" / model_name,
        PATHS.root / "config" / model_name,
        PATHS.models_dir / model_name
    ]
    for p in search_paths:
        if p.exists():
            return p
    return None

def download_file_with_progress(url: str, dest_path: Path):
    print(f"[ModelManager] 正在從 {url} 下載模型...")
    import hashlib
    try:
        existing_size = dest_path.stat().st_size if dest_path.exists() else 0
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        if existing_size > 0:
            req.add_header('Range', f'bytes={existing_size}-')
            
        with urllib.request.urlopen(req) as response:
            total_size_header = response.info().get('Content-Length')
            content_range = response.info().get('Content-Range')
            
            if content_range:
                # e.g., bytes 200-1000/1000
                total_size = int(content_range.split('/')[-1])
            elif total_size_header:
                total_size = int(total_size_header) + existing_size
            else:
                total_size = 0

            if existing_size > 0 and existing_size == total_size:
                print("\n[ModelManager] 檔案已存在且完整，略過下載。")
            else:
                downloaded = existing_size
                block_size = 8192
                mode = 'ab' if existing_size > 0 else 'wb'
                with open(dest_path, mode) as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        downloaded += len(buffer)
                        if total_size > 0:
                            percent = downloaded * 100 / total_size
                            print(f"\r[ModelManager] 下載進度: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='')
                print("\n[ModelManager] 下載完成！")
            
            # Size check
            if total_size > 0 and dest_path.stat().st_size != total_size:
                dest_path.unlink()
                raise RuntimeError(f"檔案大小校驗失敗: 預期 {total_size} bytes，實際 {dest_path.stat().st_size} bytes。")
            
            # Hash check if available in version.json
            from config import VERSION
            if VERSION.model_hash:
                print("[ModelManager] 正在校驗檔案完整性 (SHA256)...")
                sha256 = hashlib.sha256()
                with open(dest_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        sha256.update(chunk)
                if sha256.hexdigest() != VERSION.model_hash:
                    dest_path.unlink()
                    raise RuntimeError("檔案 Hash 校驗失敗，模型檔案可能損壞。")
                print("[ModelManager] 檔案校驗通過！")

    except urllib.error.HTTPError as e:
        if e.code == 416: # Range Not Satisfiable
            print("\n[ModelManager] 斷點續傳範圍無效，重新下載。")
            if dest_path.exists():
                dest_path.unlink()
            download_file_with_progress(url, dest_path)
        else:
            raise RuntimeError(f"模型下載失敗 (HTTP {e.code}): {e}")
    except Exception as e:
        raise RuntimeError(f"模型下載發生錯誤: {e}")

def try_download_model_from_huggingface(dest_dir: Path) -> Path | None:
    url = "https://huggingface.co/opendatalab/PDF-Extract-Kit-1.0/resolve/main/models/MFD/YOLO/yolo_v8_ft.pt"
    dest_path = dest_dir / "yolo_v8_ft.pt"
    print(f"[ModelManager] 嘗試從 Hugging Face 下載模型... ({url})")
    try:
        download_file_with_progress(url, dest_path)
        return dest_path
    except Exception as e:
        print(f"[ModelManager] 從 Hugging Face 下載失敗: {e}")
        return None

def convert_pt_to_onnx(pt_path: Path) -> Path | None:
    print(f"[ModelManager] 嘗試將 {pt_path.name} 轉換為 ONNX 格式...")
    try:
        from ultralytics import YOLO
        model = YOLO(str(pt_path))
        onnx_file = model.export(format='onnx')
        if onnx_file:
            return Path(onnx_file)
    except ImportError:
        print("[ModelManager] 缺少 ultralytics 套件，無法自動轉換為 ONNX，將保持 PyTorch 模式。")
    except Exception as e:
        print(f"[ModelManager] ONNX 轉換失敗: {e}")
    return None

def try_download_model_from_github(dest_dir: Path) -> Path | None:
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    print(f"[ModelManager] 嘗試查詢 GitHub Releases 以獲取模型... ({api_url})")
    
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'PDF-Toolkit-App'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            assets = data.get('assets', [])
            
            target_asset = None
            for asset in assets:
                if asset.get('name') == DEFAULT_MODEL_NAME:
                    target_asset = asset
                    break
            if not target_asset:
                for asset in assets:
                    if asset.get('name') == DEFAULT_PT_NAME:
                        target_asset = asset
                        break
                        
            if target_asset:
                download_url = target_asset.get('browser_download_url')
                file_name = target_asset.get('name')
                dest_path = dest_dir / file_name
                download_file_with_progress(download_url, dest_path)
                return dest_path
            else:
                print(f"[ModelManager] 在最新的 Release 中找不到模型檔案 ({DEFAULT_MODEL_NAME} 或 {DEFAULT_PT_NAME})")
                return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[ModelManager] 尚未發布任何 GitHub Release。無法自動下載模型。")
        else:
            print(f"[ModelManager] GitHub API 查詢失敗: HTTP {e.code}")
    except Exception as e:
        print(f"[ModelManager] 查詢更新時發生異常: {e}")
    return None

def ensure_model_ready() -> dict:
    """
    Check model status and prepare it.
    Returns:
        dict: {"status": "ready"|"fallback"|"missing", "path": Path_object_or_None, "engine": "onnx"|"pt"|"none"}
    """
    PATHS.models_dir.mkdir(parents=True, exist_ok=True)
    
    onnx_path = _get_exact_model_path(DEFAULT_MODEL_NAME)
    if onnx_path:
        print(f"[Model Check] 找到 ONNX 模型: {onnx_path}")
        return {"status": "ready", "path": onnx_path, "engine": "onnx"}
        
    pt_path = _get_exact_model_path(DEFAULT_PT_NAME)
    if pt_path:
        print(f"[Model Check] 找到 PyTorch 模型: {pt_path}")
        onnx_path = convert_pt_to_onnx(pt_path)
        if onnx_path and onnx_path.exists():
            return {"status": "ready", "path": onnx_path, "engine": "onnx"}
        print("[Model Check] 將以 PyTorch (.pt) 模式 Fallback 執行。")
        return {"status": "fallback", "path": pt_path, "engine": "pt"}
            
    # Model is completely missing. Try to download.
    print("[Model Check] 本機無任何公式檢測模型，開始自動下載...")
    downloaded_path = try_download_model_from_huggingface(PATHS.models_dir)
    if not downloaded_path:
        downloaded_path = try_download_model_from_github(PATHS.models_dir)
        
    if downloaded_path:
        if downloaded_path.suffix == ".pt":
            onnx_path = convert_pt_to_onnx(downloaded_path)
            if onnx_path and onnx_path.exists():
                return {"status": "ready", "path": onnx_path, "engine": "onnx"}
            return {"status": "fallback", "path": downloaded_path, "engine": "pt"}
        elif downloaded_path.suffix == ".onnx":
            return {"status": "ready", "path": downloaded_path, "engine": "onnx"}
            
    print("=========================================")
    print("[ERROR] 模型載入失敗！")
    print(f"無法從 GitHub 自動下載模型，請手動將 {DEFAULT_MODEL_NAME} 或 {DEFAULT_PT_NAME}")
    print(f"放置於目錄: {PATHS.models_dir}")
    print("=========================================")
    return {"status": "missing", "path": None, "engine": "none"}

if __name__ == "__main__":
    ensure_model_ready()
