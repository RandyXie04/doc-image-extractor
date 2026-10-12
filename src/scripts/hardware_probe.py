import json
import os
import subprocess
import sys
import socket
import datetime
from pathlib import Path

try:
    from src.utils.path_helper import get_config_dir
except ImportError:
    _fallback_root = Path(__file__).parent.parent.parent.resolve()
    if str(_fallback_root) not in sys.path:
        sys.path.insert(0, str(_fallback_root))
    from src.utils.path_helper import get_config_dir

CONFIG_DIR = get_config_dir()
PROFILE_PATH = CONFIG_DIR / ".hardware_profile.json"

def is_online(timeout=1.5):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except OSError:
        return False

def get_gpu_info():
    """Returns the name of the discrete GPU if found, else None"""
    try:
        cmd = ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        names = result.stdout.strip().split('\n')
        for name in names:
            name = name.strip()
            if any(k in name for k in ["RTX", "GTX", "GeForce", "Tesla", "Quadro", "Radeon"]):
                return name
    except Exception:
        pass
    return None

def get_ort_providers():
    """Returns available execution providers for ONNX Runtime (YOLO formula extraction)"""
    try:
        if 'onnxruntime' in sys.modules:
            del sys.modules['onnxruntime']
        import onnxruntime as ort
        import importlib
        importlib.reload(ort)
        if hasattr(ort, 'get_available_providers'):
            return ort.get_available_providers()
        return []
    except Exception:
        return []

def install_directml():
    """Installs onnxruntime-directml for Windows GPU acceleration"""
    if getattr(sys, 'frozen', False):
        return False
        
    print("[HardwareProbe] Discrete GPU detected. Installing DirectML accelerator...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "onnxruntime", "onnxruntime-gpu", "-y"], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "onnxruntime-directml"], check=True)
        return True
    except Exception as e:
        print(f"[HardwareProbe] DirectML installation failed: {e}")
        return False

def get_torch_accelerator():
    """Probe PyTorch CUDA / DirectML / CPU acceleration status for OCR dual channels"""
    try:
        import torch
        if torch.cuda.is_available():
            dev_name = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            vram_gb = round(props.total_memory / (1024**3), 1)
            return {
                "device": "cuda",
                "name": "CUDA",
                "device_name": dev_name,
                "vram_gb": vram_gb,
                "is_accelerated": True,
                "batch_size_rec": 16,
                "batch_size_det": 16
            }
    except Exception:
        pass
        
    return {
        "device": "cpu",
        "name": "CPU",
        "device_name": "CPU",
        "vram_gb": 0.0,
        "is_accelerated": False,
        "batch_size_rec": 2,
        "batch_size_det": 2
    }

def ensure_optimal_accelerator(force_reprobe=False):
    """
    Probe hardware for all channels (Formula + OCR + Vector text),
    persist unified hardware profile to cache, and return profile.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if not force_reprobe and PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            # If cache has full structure, return cached
            if "formula_accelerator" in cached and "ocr_accelerator" in cached:
                # Fast verification: if OCR was cuda, ensure torch.cuda is still true
                if cached["ocr_accelerator"].get("is_accelerated"):
                    import torch
                    if not torch.cuda.is_available():
                        # Environment changed, reprobe
                        pass
                    else:
                        return cached
                else:
                    return cached
        except Exception:
            pass

    # 1. GPU Name
    gpu_name = get_gpu_info()
    
    # 2. Formula Extraction (ONNX Runtime / DirectML)
    providers = get_ort_providers()
    formula_accel = False
    formula_provider = 'CPUExecutionProvider'
    formula_name = 'CPU'

    if gpu_name:
        if 'DmlExecutionProvider' not in providers:
            if is_online():
                success = install_directml()
                if success and 'DmlExecutionProvider' in get_ort_providers():
                    formula_accel = True
                    formula_provider = 'DmlExecutionProvider'
                    formula_name = 'DirectML'
        else:
            formula_accel = True
            formula_provider = 'DmlExecutionProvider'
            formula_name = 'DirectML'

    # 3. OCR Dual Channels (PyTorch / CUDA)
    ocr_info = get_torch_accelerator()

    # Determine global display name
    accel_tags = []
    if formula_accel:
        accel_tags.append(formula_name)
    if ocr_info["is_accelerated"]:
        accel_tags.append(ocr_info["name"])
    
    target_accelerator = "+".join(accel_tags) if accel_tags else "CPU"
    is_accelerated = formula_accel or ocr_info["is_accelerated"]

    profile = {
        "gpu_name": gpu_name or ocr_info.get("device_name") or "CPU / Standard Display",
        "target_accelerator": target_accelerator,
        "active_provider": formula_provider,
        "vram_gb": ocr_info.get("vram_gb", 8.0 if gpu_name else 0.0),
        "is_accelerated": is_accelerated,
        "formula_accelerator": {
            "name": formula_name,
            "provider": formula_provider,
            "is_accelerated": formula_accel
        },
        "ocr_accelerator": ocr_info,
        "last_probed": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        with open(PROFILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[HardwareProbe] 無法寫入快取: {e}")

    return profile

def get_best_providers():
    """Return the prioritized list of ORT providers for formula extraction."""
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            if profile.get('active_provider') == 'DmlExecutionProvider':
                return ['DmlExecutionProvider', 'CPUExecutionProvider']
        except Exception:
            pass
    return ['CPUExecutionProvider']

def get_ocr_accelerator_config():
    """
    Returns (device_str, rec_batch_size, det_batch_size) for Surya OCR.
    Prioritizes CUDA if available, falls back gracefully to CPU.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", 16, 16
    except Exception:
        pass
        
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                p = json.load(f)
            ocr = p.get('ocr_accelerator', {})
            if ocr.get('is_accelerated') and ocr.get('device') == 'cuda':
                import torch
                if torch.cuda.is_available():
                    return "cuda", ocr.get("batch_size_rec", 16), ocr.get("batch_size_det", 16)
        except Exception:
            pass

    return "cpu", 2, 2

if __name__ == "__main__":
    prof = ensure_optimal_accelerator(force_reprobe=True)
    print("\n[HardwareProbe Probe Result]")
    print(json.dumps(prof, indent=2, ensure_ascii=False))
