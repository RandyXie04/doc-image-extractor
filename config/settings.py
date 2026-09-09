# // ==============================================================================
# // config.py: Project Configuration Hub
# // - Paths: Dynamically resolved via pathlib(__file__).
# // - API Keys & Settings: Loaded from .env.
# // ==============================================================================

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv
import sys

# // Anchor project root: supports PyInstaller frozen execution
if getattr(sys, 'frozen', False):
    _PROJECT_ROOT = Path(sys.executable).parent.resolve()
    _BUNDLE_ROOT = Path(sys._MEIPASS).resolve() if hasattr(sys, '_MEIPASS') else _PROJECT_ROOT
else:
    _PROJECT_ROOT = Path(__file__).parent.parent.resolve()
    _BUNDLE_ROOT = _PROJECT_ROOT

# // Load .env from project root if available
load_dotenv(_PROJECT_ROOT / ".env", override=False)


# // Dynamic Path Configurations
@dataclass(frozen=True)
class _Paths:
    root:           Path = _PROJECT_ROOT
    bundle_root:    Path = _BUNDLE_ROOT
    data_dir:       Path = _PROJECT_ROOT / "data"

    # // Input area
    input_dir:      Path = _PROJECT_ROOT / "data" / "01_input"

    # // Output area
    formula_dir:    Path = _PROJECT_ROOT / "data" / "02_intermediate" / "extracted_formulas_mfd"
    formula_dir_v2: Path = _PROJECT_ROOT / "data" / "02_intermediate" / "extracted_formulas_mfd-2"
    cleaned_dir:    Path = _PROJECT_ROOT / "data" / "03_output" / "AI_Image_Processed"
    preview_dir:    Path = _PROJECT_ROOT / "data" / "02_intermediate" / "previews"
    backup_dir:     Path = _PROJECT_ROOT / "data" / "03_output" / "backup_originals"

    # // Temporary files
    temp_pdf:       Path = _PROJECT_ROOT / "data" / "02_intermediate" / "temp_cropped_optimized.pdf"

    # // ZIP outputs
    zip_mfd:        Path = _PROJECT_ROOT / "data" / "03_output" / "all_pdf_formulas_ai_mfd.zip"
    zip_hybrid:     Path = _PROJECT_ROOT / "data" / "03_output" / "all_pdf_formulas_hybrid.zip"

    # // Models
    models_dir:     Path = _PROJECT_ROOT / "models"

    def get_model_path(self, model_name: str = "yolo_v8_ft.pt") -> Path | None:
        """
        Priority:
        1. sys._MEIPASS / models / model_name
        2. current execution dir / models / model_name
        3. config / model_name
        """
        search_paths = [
            self.bundle_root / "models" / model_name,
            Path.cwd() / "models" / model_name,
            self.root / "config" / model_name
        ]
        
        # Also check alternative extension (.onnx <-> .pt)
        alt_name = model_name.replace(".pt", ".onnx") if ".pt" in model_name else model_name.replace(".onnx", ".pt")
        search_paths.extend([
            self.bundle_root / "models" / alt_name,
            Path.cwd() / "models" / alt_name,
            self.root / "config" / alt_name
        ])
        
        for p in search_paths:
            if p.exists():
                return p
        return None

    def ensure_all(self) -> None:
        # // Create all output directories
        dirs = [
            self.input_dir, self.formula_dir, self.formula_dir_v2,
            self.cleaned_dir, self.preview_dir, self.backup_dir,
            self.models_dir
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

@dataclass(frozen=True)
class _AppVersion:
    app_version: str = "1.0.0"
    model_version: str = "1.0.0"
    model_hash: str = ""
    min_compatible_model: str = "1.0.0"

def _load_version() -> _AppVersion:
    import json
    # // Try CWD first, then Project Root
    v_paths = [Path.cwd() / "version.json", _PROJECT_ROOT / "version.json", _BUNDLE_ROOT / "version.json"]
    for v_path in v_paths:
        if v_path.exists():
            try:
                with open(v_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return _AppVersion(
                        app_version=data.get("app_version", "1.0.0"),
                        model_version=data.get("model_version", "1.0.0"),
                        model_hash=data.get("model_hash", ""),
                        min_compatible_model=data.get("min_compatible_model", "1.0.0")
                    )
            except Exception:
                pass
    return _AppVersion()



# // AI Model API Keys (Loaded from .env)
@dataclass(frozen=True)
class _AIKeys:
    openai_key:        str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    gemini_key:        str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    anthropic_key:     str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    custom_llm_url:    str | None = field(default_factory=lambda: os.getenv("CUSTOM_LLM_BASE_URL"))
    custom_llm_key:    str | None = field(default_factory=lambda: os.getenv("CUSTOM_LLM_API_KEY"))
    default_model:     str        = field(default_factory=lambda: os.getenv("DEFAULT_AI_MODEL", "gpt-4o"))

    def is_openai_ready(self) -> bool:
        return bool(self.openai_key)

    def is_gemini_ready(self) -> bool:
        return bool(self.gemini_key)

    def is_anthropic_ready(self) -> bool:
        return bool(self.anthropic_key)


# // Behavior and Guardrail Settings
@dataclass(frozen=True)
class _Config:
    use_gpu:        bool  = field(default_factory=lambda: os.getenv("USE_GPU", "true").lower() == "true")
    formula_dpi:    int   = field(default_factory=lambda: int(os.getenv("FORMULA_DPI", "300")))
    header_ratio:   float = field(default_factory=lambda: float(os.getenv("HEADER_RATIO", "0.15")))
    footer_ratio:   float = field(default_factory=lambda: float(os.getenv("FOOTER_RATIO", "0.92")))
    left_ratio:     float = field(default_factory=lambda: float(os.getenv("LEFT_RATIO", "0.0")))
    right_ratio:    float = field(default_factory=lambda: float(os.getenv("RIGHT_RATIO", "0.0")))
    extract_inline: bool  = field(default_factory=lambda: os.getenv("EXTRACT_INLINE", "false").lower() == "true")
    embed_formulas_in_word: bool = field(default_factory=lambda: os.getenv("EMBED_FORMULAS_IN_WORD", "true").lower() == "true")
    easyocr_langs:  list  = field(default_factory=lambda: os.getenv("EASYOCR_LANGS", "ch_sim,en").split(","))
    
    # // Resource guardrails
    max_safe_pages: int   = field(default_factory=lambda: int(os.getenv("MAX_SAFE_PAGES", "300")))
    batch_size:     int   = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "50")))
    max_image_width:int   = field(default_factory=lambda: int(os.getenv("MAX_IMAGE_WIDTH", "4000")))
    
    def get_hardware_profile(self) -> dict:
        import json
        profile_path = _PROJECT_ROOT / "config" / ".hardware_profile.json"
        if profile_path.exists():
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "gpu_name": "Unknown",
            "target_accelerator": "CPU",
            "active_provider": "CPUExecutionProvider",
            "vram_gb": 0.0,
            "is_accelerated": False
        }


PATHS   = _Paths()
AI      = _AIKeys()
CFG     = _Config()
VERSION = _load_version()


if __name__ == "__main__":
    print("=" * 60)
    print("[Paths] Dynamic Paths Configuration")
    print("=" * 60)
    for attr, val in PATHS.__dataclass_fields__.items():
        path: Path = getattr(PATHS, attr)
        if isinstance(path, Path):
            status = "[EXISTS]" if path.exists() else "[MISSING]"
            print(f"  {attr:<20} {status}  {path}")

    print()
    print("=" * 60)
    print("[AI Keys] API Key Status")
    print("=" * 60)
    print(f"  OpenAI   : {'[READY]' if AI.is_openai_ready()    else '[NOT SET (OPENAI_API_KEY)]'}")
    print(f"  Gemini   : {'[READY]' if AI.is_gemini_ready()    else '[NOT SET (GEMINI_API_KEY)]'}")
    print(f"  Anthropic: {'[READY]' if AI.is_anthropic_ready() else '[NOT SET (ANTHROPIC_API_KEY)]'}")
    print(f"  Default Model: {AI.default_model}")

    print()
    print("=" * 60)
    print("[Config] Behavior Settings")
    print("=" * 60)
    print(f"  USE_GPU       : {CFG.use_gpu}")
    print(f"  FORMULA_DPI   : {CFG.formula_dpi}")
    print(f"  HEADER_RATIO  : {CFG.header_ratio}")
    print(f"  FOOTER_RATIO  : {CFG.footer_ratio}")
    print(f"  EASYOCR_LANGS : {CFG.easyocr_langs}")

