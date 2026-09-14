# 智慧雙引擎 PDF 轉檔與 OCR 管線

本目錄包含 PDF 排版解析、雙引擎切換與 OCR 處理的相關腳本。

## ⚡ 核心功能

*   **智慧型雙引擎自動分流 (`pdf_engine_dispatcher.py`)**：
    *   **高速原生向量引擎 (PyMuPDF)**：自動採樣文件前段文字密度。若判定為原生文字型 PDF，直接切換高速文字流抽取，跳過耗時龐大的深度學習 OCR，速度提升 10 倍以上且記憶體極度輕量。
    *   **深度排版 OCR 引擎 (RapidDoc)**：若偵測為掃描書籍、純圖或轉曲 PDF，無縫切換至 RapidDoc 深度模型 (`process_ocr.py`)，精準進行版面分析、表格抽取與繁簡中文辨識。
    *   **UI 模式自選**：支援在前端下拉選單中手動強制指定「自動偵測」、「高速提取 (PyMuPDF)」或「深度識別 (RapidDoc)」。
*   **邊界裁切微調控制 (Margin Ratio Sliders)**：
    *   介面提供「左側裁切比例」與「右側裁切比例」滑桿，精準裁除書籍掃描時常見的裝訂線黑邊、陰影或邊緣雜訊。
*   **即時進度條與伺服器回報 (Real-time Progress Reporting)**：
    *   提供真實後端進度追蹤端點（`/api/ocr_progress/{stem}`），視覺化顯示分析進度百分比與即時狀態訊息。
*   **幾何與語意啟發式標題偵測 (`HeadingDetector`)**：
    *   結合字體大小、排版幾何特徵（置中對齊、單行字數、粗體、前後間距）與章節正則規則，將各級標題精準升級為 Markdown 語意（`#`、`##`、`###`）。
*   **自訂 Word 樣式範本與視覺化大綱編輯器 (Outline Editor)**：
    *   支援上傳自訂範本 (`.docx`) 進行樣式下拉對應，轉檔後於介面動態調整各段落階層（H1/H2/H3/內文），支援一鍵重新產出最終 Word 文件 (`md_to_docx.py`)。

## 🚀 主要腳本
- `pdf_engine_dispatcher.py`: 智慧雙引擎排程與派發器。
- `process_ocr.py`: 負責深度版面 OCR 分析。
- `md_to_docx.py`: 將解析後的 Markdown 轉換為樣式化的 Word 檔。
