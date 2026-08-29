# 🧠 專案技能與核心能力庫 (SKILLS.md)

本文件整理本專案內建的核心技術技能（Domain Skills）、AI 模型工具與開發能力，供開發者與協作 Agent 快速掌握專案能力邊界。

---

## 1. 核心 AI 與影像處理技能 (Core AI Skills)

### 📐 數學公式物件偵測 (Pix2Text MFD)
* **技術棧**：`pix2text.MathFormulaDetector` (基於 YOLO / LayoutLM 深度學習架構)
* **核心能力**：
  * 自動分析 PDF 頁面圖片，精準識別獨立公式區塊 (Display Math / Isolated Formula)。
  * 支援動態邊界裁切，將偵測到的 Bounding Box 裁切並儲存為高解析度透明/白底 PNG。
  * 命名規範：`p{page:03d}_eq{index:02d}.png`。

### ✂️ PDF 動態頁面裁切與版面分析 (Dynamic PDF Cropping)
* **技術棧**：`PyMuPDF (fitz)` + `OpenCV` + `NumPy`
* **核心能力**：
  * 自動探測 PDF 頁首（Header）與頁尾（Footer）干擾資訊（如頁碼、章節名稱、印刷浮水印）。
  * 依據比例（預設 0.10）或視覺化滑桿參數，動態計算每頁裁切矩形 (`set_cropbox`)。
  * 支援抽樣驗證報告生成（Sampling Verification Report）。

### 📄 PDF 轉 Word 排版引擎 (PDF to DOCX Engine)
* **技術棧**：`pdf2docx.Converter` + `python-docx`
* **核心能力**：
  * 將裁切後的 PDF 轉換為可編輯的 Microsoft Word (.docx) 格式。
  * 內建 **CMYK 色彩空間修補 (Monkey Patch)**，遇到四通道印刷圖片自動轉碼 RGB，避免轉檔中斷。

---

## 2. 系統架構與防護技能 (System & Guardrail Skills)

### 🛡️ 資源限制防爆機制 (Resource Guardrails)
* **動態 DPI 縮放**：當 PDF 頁面寬度超過 `MAX_IMAGE_WIDTH` (4000px) 時，自動降低渲染 DPI，避免記憶體溢出。
* **分批記憶體回收**：每處理 `BATCH_SIZE` (50 頁) 強制調用 `gc.collect()` 與 `torch.cuda.empty_cache()`。
* **頁數安全閥**：限制單次處理上限 `MAX_SAFE_PAGES` (300 頁)，過長文檔自動截斷保護。

### 📦 自動化成品打包與交付 (Automated Packaging)
* 輸出標準結構：`data/03_output/{base_name}_{timestamp}/`
* 自動將轉換後之 `.docx` 檔案與包含所有公式圖之 `formulas.zip` 打包為最終發布封包。

---

## 3. Web 介面與前後端互動技能 (Web Architecture Skills)

### ⚡ FastAPI 非同步處理後端
* **技術棧**：`FastAPI` + `Uvicorn` + `BackgroundTasks`
* **端點設計**：
  * `POST /api/upload_file`：非同步上傳並取得 `file_id`。
  * `GET /api/render_preview/{file_id}`：動態即時渲染裁切紅藍輔助線。
  * `POST /api/process`：非同步佇列任務處理。
  * `GET /api/status/{task_id}`：進度與 Log 輪詢。
  * `GET /api/download/{task_id}`：成品封包下載。

### 🎨 原生前端互動體驗 (Vanilla Web UI)
* 拖曳上傳 (Drag & Drop)。
* 動態滑桿即時輔助線預覽 (Real-time Canvas/Image Preview with Debounce)。
* 終端日誌控制台 (Terminal Log Streaming)。
* **一鍵 GitHub Issue 回報器**：發生例外時自動格式化錯誤 Traceback 與設定參數至 GitHub Issue。
