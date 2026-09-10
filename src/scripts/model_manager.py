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
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get('Content-Length', 0))
            downloaded = 0
            block_size = 8192
            
            with open(dest_path, 'wb') as f:
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
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink()
        raise RuntimeError(f"模型下載失敗: {e}")

def try_download_model_from_github(dest_dir: Path) -> Path | None:
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    print(f"[ModelManager] 嘗試查詢 GitHub Releases 以獲取模型... ({api_url})")
    
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'PDF-Toolkit-App'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            assets = data.get('assets', [])
            
            # Try to find .onnx first, then .pt
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
                print("[ModelManager] 在最新的 Release 中找不到模型檔案 (yolo_v8_ft.onnx 或 .pt)")
                return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[ModelManager] 尚未發布任何 GitHub Release。無法自動下載模型。")
        else:
            print(f"[ModelManager] GitHub API 查詢失敗: HTTP {e.code}")
    except Exception as e:
        print(f"[ModelManager] 查詢更新時發生異常: {e}")
    return None

def export_pt_to_onnx(pt_path: Path) -> Path | None:
    print(f"[ModelManager] 偵測到 PyTorch 模型 ({pt_path.name})，準備自動導出為 ONNX 格式...")
    try:
        from ultralytics import YOLO
        model = YOLO(str(pt_path))
        print("[ModelManager] 正在轉換，這可能需要幾分鐘...")
        # export to ONNX
        success_path = model.export(format="onnx", dynamic=True, imgsz=1888)
        
        if success_path and Path(success_path).exists():
            print(f"[ModelManager] ONNX 轉換成功: {success_path}")
            return Path(success_path)
        else:
            # Fallback path if ultralytics didn't return the path but generated it
            expected_onnx = pt_path.with_suffix('.onnx')
            if expected_onnx.exists():
                print(f"[ModelManager] ONNX 轉換成功 (於預期路徑): {expected_onnx}")
                return expected_onnx
            print("[ModelManager] 轉換完成但找不到輸出的 ONNX 檔案。")
            return None
    except ImportError:
        print("[ModelManager] 系統未安裝 ultralytics，無法自動將 .pt 轉換為 .onnx。將嘗試直接使用 PyTorch 推論。")
    except Exception as e:
        print(f"[ModelManager] 轉換過程中發生錯誤: {e}")
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
        # We have .pt but no .onnx. Try to export.
        onnx_exported = export_pt_to_onnx(pt_path)
        if onnx_exported:
            # Move the exported ONNX to models_dir if it's not already there
            if onnx_exported.parent != PATHS.models_dir and onnx_exported.parent != pt_path.parent:
                 try:
                     target_path = PATHS.models_dir / onnx_exported.name
                     shutil.move(str(onnx_exported), str(target_path))
                     return {"status": "ready", "path": target_path, "engine": "onnx"}
                 except Exception:
                     return {"status": "ready", "path": onnx_exported, "engine": "onnx"}
            return {"status": "ready", "path": onnx_exported, "engine": "onnx"}
        else:
            print("[Model Check] 無法取得 ONNX 模型，將以 PyTorch (.pt) 模式 Fallback 執行。")
            return {"status": "fallback", "path": pt_path, "engine": "pt"}
            
    # Model is completely missing. Try to download.
    print("[Model Check] 本機無任何公式檢測模型，開始自動下載...")
    downloaded_path = try_download_model_from_github(PATHS.models_dir)
    if downloaded_path:
        if downloaded_path.suffix == ".onnx":
            return {"status": "ready", "path": downloaded_path, "engine": "onnx"}
        elif downloaded_path.suffix == ".pt":
            onnx_exported = export_pt_to_onnx(downloaded_path)
            if onnx_exported:
                return {"status": "ready", "path": onnx_exported, "engine": "onnx"}
            return {"status": "fallback", "path": downloaded_path, "engine": "pt"}
            
    print("=========================================")
    print("[ERROR] 模型載入失敗！")
    print("無法從 GitHub 自動下載模型，請手動將 yolo_v8_ft.onnx 或 yolo_v8_ft.pt")
    print(f"放置於目錄: {PATHS.models_dir}")
    print("=========================================")
    return {"status": "missing", "path": None, "engine": "none"}

if __name__ == "__main__":
    ensure_model_ready()
