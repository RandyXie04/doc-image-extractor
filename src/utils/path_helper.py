import sys
from pathlib import Path

def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

def get_project_dir() -> Path:
    """專案根目錄 (<project_root>/src/utils/path_helper.py)"""
    return Path(__file__).resolve().parents[2]

def get_app_dir() -> Path:
    """應用程式根目錄"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return get_project_dir()

def get_bundle_dir() -> Path:
    """資源目錄"""
    if is_frozen():
        return Path(sys._MEIPASS).resolve()
    return get_project_dir()

# --- 語意化資源路徑介面 ---
def get_config_dir() -> Path:
    return get_app_dir() / "config"

def get_models_dir() -> Path:
    return get_app_dir() / "models"

def get_data_dir() -> Path:
    return get_app_dir() / "data"

def get_log_dir() -> Path:
    return get_app_dir() / "logs" # 獨立出 logs 資料夾

def get_scratch_dir() -> Path:
    return get_app_dir() / "scratch"

# --- Bundle 內部資源 (須與 build_app.spec 'datas' 嚴格對應) ---
# Spec: ('src/web/static', 'src/web/static')
def get_static_dir() -> Path:
    return get_bundle_dir() / "src" / "web" / "static"
    
# Spec: ('src/founder_tools/template.docx', 'src/founder_tools')
def get_template_path() -> Path:
    return get_bundle_dir() / "src" / "founder_tools" / "template.docx"

# Spec: ('bin/pandoc.exe', 'bin')
def get_bundled_pandoc() -> Path:
    return get_bundle_dir() / "bin" / "pandoc.exe"
