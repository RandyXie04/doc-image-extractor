import os
import urllib.request
import urllib.parse
import json
import urllib.error
import threading
from pathlib import Path

# Add project root to path
from config import PATHS

GITHUB_REPO = 'RandyXie04/doc-image-extractor'
DEFAULT_MODEL_NAME = "pdf_extract_mfd.onnx"
LEGACY_MODEL_NAME = "yolo_v8_ft.onnx"
DEFAULT_PT_NAME = "yolo_v8_ft.pt"
SURYA_MODELS = {
    "surya_det3": "vikp/surya_det3",
    "surya_rec2": "vikp/surya_rec2",
    "surya_layout0": "datalab-to/surya_layout0",
}
_model_lock = threading.Lock()

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

def download_file_with_progress(url: str, dest_path: Path, max_retries: int = 5, verify_hash: bool = True):
    import hashlib
    import time
    
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported download URL scheme: {parsed_url.scheme!r}")

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"[ModelManager] 網路中斷，正在進行第 {attempt} 次重試...")
                time.sleep(2)
                
            print(f"[ModelManager] 正在從 {url} 下載模型...")
            existing_size = dest_path.stat().st_size if dest_path.exists() else 0
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            if existing_size > 0:
                req.add_header('Range', f'bytes={existing_size}-')
                
            with urllib.request.urlopen(req, timeout=15) as response:  # nosec B310 - scheme validated above
                total_size_header = response.info().get('Content-Length')
                content_range = response.info().get('Content-Range')
                
                if content_range:
                    total_size = int(content_range.split('/')[-1])
                elif total_size_header:
                    total_size = int(total_size_header) + existing_size
                else:
                    total_size = 0

                if existing_size > 0 and existing_size == total_size:
                    print("\n[ModelManager] 檔案已存在且完整，略過下載。")
                    return
                
                downloaded = existing_size
                block_size = 1048576  # 1MB
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
                if total_size > 0 and dest_path.exists() and dest_path.stat().st_size != total_size:
                    raise RuntimeError(f"檔案大小校驗失敗: 預期 {total_size} bytes，實際 {dest_path.stat().st_size} bytes。")
                
                # Hash check if available in version.json
                from config import VERSION
                if verify_hash and VERSION.model_hash and VERSION.model_hash != "sha256:default":
                    print("[ModelManager] 正在校驗檔案完整性 (SHA256)...")
                    sha256 = hashlib.sha256()
                    with open(dest_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(4096), b""):
                            sha256.update(chunk)
                            
                    expected_hash = VERSION.model_hash.replace("sha256:", "").strip()
                    if sha256.hexdigest() != expected_hash:
                        if dest_path.exists():
                            dest_path.unlink()
                        raise RuntimeError("檔案 Hash 校驗失敗，模型檔案可能損壞。")
                    print("[ModelManager] 檔案校驗通過！")
                
                return # 成功則直接返回

        except urllib.error.HTTPError as e:
            if e.code == 416: # Range Not Satisfiable
                print("\n[ModelManager] 斷點續傳範圍無效，重新下載。")
                if dest_path.exists():
                    dest_path.unlink()
                continue # Retry from scratch
            else:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"模型下載失敗 (HTTP {e.code}): {e}")
        except Exception as e:
            if attempt == max_retries - 1:
                # 確保檔案存在再刪除，避免 WinError 2
                if dest_path.exists() and total_size > 0 and dest_path.stat().st_size != total_size:
                    try:
                        dest_path.unlink()
                    except:
                        pass
                raise RuntimeError(f"模型下載發生錯誤: {e}")
            print(f"\n[ModelManager] 下載過程發生例外 ({e})，準備重試...")


def convert_pt_to_onnx(pt_path: Path) -> Path | None:
    print(f"[ModelManager] 嘗試將 {pt_path.name} 轉換為 ONNX 格式 ({DEFAULT_MODEL_NAME}, imgsz=1280)...")
    try:
        from src.scripts.export_mfd_onnx import export_mfd_to_onnx
        return export_mfd_to_onnx(
            weights_path=pt_path,
            output_path=PATHS.models_dir / DEFAULT_MODEL_NAME,
            imgsz=1280,
            verify=True,
            force=True,
            download_if_missing=False,
        )
    except ImportError:
        print("[ModelManager] 缺少 ultralytics 或 export_mfd_onnx 依賴，無法自動轉換為 ONNX，將保持 PyTorch 模式。")
    except Exception as e:
        print(f"[ModelManager] ONNX 轉換失敗: {e}")
    return None

def try_download_model_from_github(dest_dir: Path) -> Path | None:
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    print(f"[ModelManager] 嘗試查詢 GitHub Releases 以獲取模型... ({api_url})")
    
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'PDF-Toolkit-App'})
        with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310 - hardcoded https GitHub API URL
            data = json.loads(response.read().decode('utf-8'))
            assets = data.get('assets', [])
            
            target_asset = None
            for candidate_name in (DEFAULT_MODEL_NAME, LEGACY_MODEL_NAME, DEFAULT_PT_NAME):
                for asset in assets:
                    if asset.get('name') == candidate_name:
                        target_asset = asset
                        break
                if target_asset:
                    break
                        
            if target_asset:
                download_url = target_asset.get('browser_download_url')
                file_name = target_asset.get('name')
                dest_path = dest_dir / file_name
                temp_path = dest_dir / f"{file_name}.downloading"
                download_file_with_progress(
                    download_url,
                    temp_path,
                    verify_hash=(file_name == DEFAULT_MODEL_NAME),
                )
                if temp_path.exists():
                    temp_path.replace(dest_path)
                return dest_path
            else:
                print(f"[ModelManager] 在最新的 Release 中找不到模型檔案 ({DEFAULT_MODEL_NAME} / {LEGACY_MODEL_NAME} / {DEFAULT_PT_NAME})")
                return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[ModelManager] 尚未發布任何 GitHub Release。無法自動下載模型。")
        else:
            print(f"[ModelManager] GitHub API 查詢失敗: HTTP {e.code}")
    except Exception as e:
        print(f"[ModelManager] 查詢更新時發生異常: {e}")
    return None

def try_download_surya_from_huggingface(dest_dir: Path) -> Path | None:
    print("[ModelManager] 嘗試從 HuggingFace 官方拉取 Surya 模型...")
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        from huggingface_hub import snapshot_download
        for folder_name, repo_id in SURYA_MODELS.items():
            dest_path = dest_dir / folder_name
            if (dest_path / "model.safetensors").exists():
                print(f"[ModelManager] 已存在本地權重，略過下載: {dest_path}")
                continue
            print(f"[ModelManager] 正在處理 {repo_id} -> {dest_path} ...")
            snapshot_download(  # nosec B615 - official Surya HuggingFace repos
                repo_id=repo_id,
                local_dir=dest_path,
                local_dir_use_symlinks=False,
                ignore_patterns=["*.onnx", "*.safetensors.onnx", "*.msgpack"]
            )
            print(f"[ModelManager] {repo_id} 完成！")
            
        print("[ModelManager] Surya 模型從 HuggingFace 下載完成！")
        return dest_dir
    except Exception as e:
        print(f"[ModelManager] 下載 Surya 模型發生異常: {e}")
        return None

def ensure_model_ready() -> dict:
    """
    Check model status and prepare it.
    Returns:
        dict: {"status": "ready"|"fallback"|"missing", "path": Path_object_or_None, "engine": "onnx"|"pt"|"none"}
    """
    if os.environ.get("SKIP_MODEL_DOWNLOAD") == "1":
        return {"status": "skipped", "path": None, "engine": "none"}

    with _model_lock:
        PATHS.models_dir.mkdir(parents=True, exist_ok=True)
    
    # 檢查 SuryaOCR 扁平本地模型是否存在
    missing_surya = [
        name for name in SURYA_MODELS
        if not (PATHS.models_dir / name / "model.safetensors").exists()
    ]
    if missing_surya:
        print(f"[Model Check] 缺少 SuryaOCR 本地權重 {missing_surya}，開始自動從 HuggingFace 下載...")
        try_download_surya_from_huggingface(PATHS.models_dir)
    else:
        print(f"[Model Check] 找到完整 SuryaOCR 本地模型: {PATHS.models_dir}")
        
    onnx_path = _get_exact_model_path(DEFAULT_MODEL_NAME) or _get_exact_model_path(LEGACY_MODEL_NAME)
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
            
    # Model is completely missing. Try GitHub Release first, then HuggingFace MFD export fallback.
    print("[Model Check] 本機無任何公式檢測模型，開始自動從 GitHub 下載...")
    downloaded_path = try_download_model_from_github(PATHS.models_dir)
        
    if downloaded_path:
        if downloaded_path.suffix == ".pt":
            onnx_path = convert_pt_to_onnx(downloaded_path)
            if onnx_path and onnx_path.exists():
                return {"status": "ready", "path": onnx_path, "engine": "onnx"}
            return {"status": "fallback", "path": downloaded_path, "engine": "pt"}
        elif downloaded_path.suffix == ".onnx":
            return {"status": "ready", "path": downloaded_path, "engine": "onnx"}

    print("[Model Check] GitHub Release 無可用模型，嘗試從 HuggingFace opendatalab/PDF-Extract-Kit-1.0 自動下載並轉檔...")
    try:
        from src.scripts.export_mfd_onnx import export_mfd_to_onnx
        exported_path = export_mfd_to_onnx(
            weights_path=PATHS.models_dir / DEFAULT_PT_NAME,
            output_path=PATHS.models_dir / DEFAULT_MODEL_NAME,
            imgsz=1280,
            verify=True,
            download_if_missing=True,
        )
        if exported_path and Path(exported_path).exists():
            return {"status": "ready", "path": Path(exported_path), "engine": "onnx"}
    except Exception as e:
        print(f"[Model Check] HuggingFace 自動下載或 ONNX 轉檔失敗: {e}")
            
    print("=========================================")
    print("[ERROR] 模型載入失敗！")
    print(f"無法自動取得模型，請手動將 {DEFAULT_MODEL_NAME} 或 {DEFAULT_PT_NAME}")
    print(f"放置於目錄: {PATHS.models_dir}")
    print("=========================================")
    return {"status": "missing", "path": None, "engine": "none"}

if __name__ == "__main__":
    ensure_model_ready()
