import sys
from pathlib import Path
from typing import Optional, Union

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

def get_data_dir() -> Path:
    return get_app_dir() / "data"

def get_scratch_dir() -> Path:
    return get_app_dir() / "scratch"

# --- Bundle 內部資源 (須與 build_app.spec 'datas' 嚴格對應) ---
# Spec: ('src/web/static', 'src/web/static')
def get_static_dir() -> Path:
    return get_bundle_dir() / "src" / "web" / "static"
    
# Spec: ('src/founder_tools/template.docx', 'src/founder_tools')
def get_template_path() -> Path:
    return get_bundle_dir() / "src" / "founder_tools" / "template.docx"

def resolve_active_template_path(
    preferred_path: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """
    動態解析當前啟用的 Word 樣式範本 (.docx) 絕對路徑。

    解析優先順序 (Fallback Hierarchy):
    1. preferred_path: 明確指定的自訂範本路徑 (若傳入且檔案存在)
    2. 使用者上傳範本: data/database_text/custom_templates/user_template.docx
    3. 資料目錄預設範本: data/database_text/template.docx
    4. 套件內建範本: src/founder_tools/template.docx (get_template_path())
    5. 設定目錄範本: config/template.docx (get_config_dir() / "template.docx")
    6. 專案根目錄範本: template.docx (get_project_dir() / "template.docx")

    Returns:
        Optional[Path]: 存在之範本 Path 物件，若皆不存在則回傳 None。
    """
    if preferred_path:
        p = Path(preferred_path)
        if p.exists() and p.is_file():
            return p.resolve()

    candidates = [
        get_data_dir() / "database_text" / "custom_templates" / "user_template.docx",
        get_data_dir() / "database_text" / "template.docx",
        get_template_path(),
        get_config_dir() / "template.docx",
        get_project_dir() / "template.docx",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    return None

# Spec: ('bin/pandoc.exe', 'bin')
def get_bundled_pandoc() -> Path:
    return get_bundle_dir() / "bin" / "pandoc.exe"
