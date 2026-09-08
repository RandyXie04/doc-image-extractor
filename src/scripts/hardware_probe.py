import json
import os
import subprocess
import sys
import socket
import datetime
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
PROFILE_PATH = CONFIG_DIR / ".hardware_profile.json"

def is_online(timeout=1.5):
    try:
        # Check against a reliable public DNS
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except OSError:
        return False

def get_gpu_info():
    """Returns the name of the discrete GPU if found, else None"""
    try:
        # Use powershell to query GPU
        # Get-CimInstance Win32_VideoController
        cmd = ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        names = result.stdout.strip().split('\n')
        for name in names:
            name = name.strip()
            if "RTX 30" in name or "RTX 40" in name or "RTX 50" in name or "RTX A" in name:
                return name
    except Exception:
        pass
    return None

def get_ort_providers():
    try:
        if 'onnxruntime' in sys.modules:
            del sys.modules['onnxruntime']
        import onnxruntime as ort
        import importlib
        importlib.reload(ort)
        return ort.get_available_providers()
    except ImportError:
        return []

def install_directml():
    print("[HardwareProbe] RTX 30+ GPU detected. Installing DirectML accelerator...")
    try:
        # Uninstall both to be safe
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "onnxruntime", "onnxruntime-gpu", "-y"], check=True)
        # Install directml
        subprocess.run([sys.executable, "-m", "pip", "install", "onnxruntime-directml"], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[HardwareProbe] Installation failed: {e}")
        return False
    except Exception as e:
        print(f"[HardwareProbe] Unexpected error during installation: {e}")
        return False

def ensure_optimal_accelerator():
    """Probe hardware, switch to DirectML if needed, and write to cache."""
    # 1. Read cache first
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            # If accelerated, ensure DmlExecutionProvider is available
            if profile.get('is_accelerated'):
                if 'DmlExecutionProvider' in get_ort_providers():
                    print("[HardwareProbe] Loaded from cache. Hardware accelerated.")
                    return profile
                else:
                    print("[HardwareProbe] Cache says accelerated, but DML provider missing. Re-evaluating...")
            else:
                print("[HardwareProbe] Loaded from cache. CPU mode.")
                return profile
        except Exception:
            pass

    # 2. Probe hardware
    gpu_name = get_gpu_info()
    providers = get_ort_providers()

    is_accelerated = False
    active_provider = 'CPUExecutionProvider'
    target_accelerator = 'CPU'

    if gpu_name:
        if 'DmlExecutionProvider' not in providers:
            if is_online():
                success = install_directml()
                if success and 'DmlExecutionProvider' in get_ort_providers():
                    is_accelerated = True
                    active_provider = 'DmlExecutionProvider'
                    target_accelerator = 'DirectML'
                else:
                    print("[HardwareProbe] Failed to install/verify DML. Falling back to CPU.")
            else:
                print("[HardwareProbe] Offline. Falling back to CPU mode.")
        else:
            is_accelerated = True
            active_provider = 'DmlExecutionProvider'
            target_accelerator = 'DirectML'
    
    profile = {
        "gpu_name": gpu_name or "Unknown / Basic Display Adapter",
        "target_accelerator": target_accelerator,
        "active_provider": active_provider,
        "vram_gb": 8.0, # Dummy for now
        "is_accelerated": is_accelerated,
        "last_probed": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(PROFILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(profile, f, indent=4)
    
    return profile

def get_best_providers():
    """Return the prioritized list of ORT providers."""
    if PROFILE_PATH.exists():
        try:
            with open(PROFILE_PATH, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            if profile.get('active_provider') == 'DmlExecutionProvider':
                return ['DmlExecutionProvider', 'CPUExecutionProvider']
        except Exception:
            pass
    return ['CPUExecutionProvider']

if __name__ == "__main__":
    ensure_optimal_accelerator()
