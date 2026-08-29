#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py ── 專案全域設定中心
==============================
設計原則：
  - 【路徑】：全部由 pathlib(__file__) 動態計算，不寫死任何絕對路徑。
              資料夾改名、移動專案、換電腦，路徑全部自動跟隨。
  - 【API 金鑰 / 設定值】：由 .env 載入，絕不寫入程式碼。

使用方式（在任何腳本中匯入）：
  from config import PATHS, AI, CFG
  
  # 取得路徑
  output_dir = PATHS.formula_dir          # Path 物件，直接可用
  pdf_src    = PATHS.input_dir / "book.pdf"

  # 取得 API 金鑰
  key = AI.openai_key

  # 取得設定值
  dpi = CFG.formula_dpi
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# 1. 錨定基準：本檔案所在目錄的上一層 = 專案根目錄
# ─────────────────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 載入同目錄下的 .env（若不存在則靜默略過，不報錯）
load_dotenv(_PROJECT_ROOT / ".env", override=False)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 路徑設定（純 pathlib，不讀 .env）
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Paths:
    """
    所有路徑均為 pathlib.Path 物件，相對於專案根目錄動態計算。
    frozen=True 確保路徑在執行期間不被意外修改。
    """
    root:           Path = _PROJECT_ROOT
    data_dir:       Path = _PROJECT_ROOT / "data"

    # ── 輸入區 ──────────────────────────────────────────────────────────────
    input_dir:      Path = _PROJECT_ROOT / "data" / "01_input"

    # ── 輸出區 ──────────────────────────────────────────────────────────────
    formula_dir:    Path = _PROJECT_ROOT / "data" / "02_intermediate" / "extracted_formulas_mfd"
    formula_dir_v2: Path = _PROJECT_ROOT / "data" / "02_intermediate" / "extracted_formulas_mfd-2"
    cleaned_dir:    Path = _PROJECT_ROOT / "data" / "03_output" / "AI_圖片處理_正式版"
    preview_dir:    Path = _PROJECT_ROOT / "data" / "02_intermediate" / "previews"
    backup_dir:     Path = _PROJECT_ROOT / "data" / "03_output" / "backup_originals"

    # ── 暫存區（臨時檔，生命週期短，也錨定在根目錄避免污染 CWD）──────────
    temp_pdf:       Path = _PROJECT_ROOT / "data" / "02_intermediate" / "temp_cropped_optimized.pdf"

    # ── ZIP 封裝輸出 ─────────────────────────────────────────────────────────
    zip_mfd:        Path = _PROJECT_ROOT / "data" / "03_output" / "all_pdf_formulas_ai_mfd.zip"
    zip_hybrid:     Path = _PROJECT_ROOT / "data" / "03_output" / "all_pdf_formulas_hybrid.zip"

    def ensure_all(self) -> None:
        """
        一次性建立所有輸出資料夾（temp_pdf 是檔案，跳過）。
        在 pipeline 最開頭呼叫一次即可。
        """
        dirs = [
            self.input_dir, self.formula_dir, self.formula_dir_v2,
            self.cleaned_dir, self.preview_dir, self.backup_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# 3. AI 模型 API 金鑰（讀自 .env，永不寫死）
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _AIKeys:
    """
    API 金鑰從 .env 讀取。
    若金鑰未設定則為 None，呼叫端應自行判斷是否可用。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# 4. 行為設定（讀自 .env，有合理預設值）
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Config:
    """
    程式執行行為參數。可透過 .env 覆蓋，不影響路徑結構。
    """
    use_gpu:        bool  = field(default_factory=lambda: os.getenv("USE_GPU", "true").lower() == "true")
    formula_dpi:    int   = field(default_factory=lambda: int(os.getenv("FORMULA_DPI", "300")))
    header_ratio:   float = field(default_factory=lambda: float(os.getenv("HEADER_RATIO", "0.15")))
    footer_ratio:   float = field(default_factory=lambda: float(os.getenv("FOOTER_RATIO", "0.92")))
    easyocr_langs:  list  = field(default_factory=lambda: os.getenv("EASYOCR_LANGS", "ch_sim,en").split(","))
    
    # ── 資源限制防護 (Guardrails) ──
    max_safe_pages: int   = field(default_factory=lambda: int(os.getenv("MAX_SAFE_PAGES", "300")))
    batch_size:     int   = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "50")))
    max_image_width:int   = field(default_factory=lambda: int(os.getenv("MAX_IMAGE_WIDTH", "4000")))


# ─────────────────────────────────────────────────────────────────────────────
# 5. 模組層級單例（直接 import 使用）
# ─────────────────────────────────────────────────────────────────────────────
PATHS = _Paths()
AI    = _AIKeys()
CFG   = _Config()


# ─────────────────────────────────────────────────────────────────────────────
# 6. 快速自我檢測（執行 python config.py 可直接驗證）
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("📁 路徑設定（全由 pathlib 動態計算）")
    print("=" * 60)
    for attr, val in PATHS.__dataclass_fields__.items():
        path: Path = getattr(PATHS, attr)
        if isinstance(path, Path):
            status = "✅ 存在" if path.exists() else "⬜ 尚不存在"
            print(f"  {attr:<20} {status}  {path}")

    print()
    print("=" * 60)
    print("🔑 AI 金鑰狀態（不顯示實際金鑰）")
    print("=" * 60)
    print(f"  OpenAI   : {'✅ 已設定' if AI.is_openai_ready()    else '❌ 未設定（OPENAI_API_KEY）'}")
    print(f"  Gemini   : {'✅ 已設定' if AI.is_gemini_ready()    else '❌ 未設定（GEMINI_API_KEY）'}")
    print(f"  Anthropic: {'✅ 已設定' if AI.is_anthropic_ready() else '❌ 未設定（ANTHROPIC_API_KEY）'}")
    print(f"  預設模型  : {AI.default_model}")

    print()
    print("=" * 60)
    print("⚙️  行為設定")
    print("=" * 60)
    print(f"  USE_GPU       : {CFG.use_gpu}")
    print(f"  FORMULA_DPI   : {CFG.formula_dpi}")
    print(f"  HEADER_RATIO  : {CFG.header_ratio}")
    print(f"  FOOTER_RATIO  : {CFG.footer_ratio}")
    print(f"  EASYOCR_LANGS : {CFG.easyocr_langs}")
