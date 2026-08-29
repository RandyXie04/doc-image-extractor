# 📄 PDF 公式萃取與轉檔工作站 (PDF Formula Extractor)

本專案是一個深度整合了 **AI 數學公式識別 (Pix2Text)** 與 **PDF 動態排版解析** 的自動化工具。主要用於將含有大量數學公式的學術 PDF 書籍或論文，完美轉換為 Word 格式，並自動將內文的獨立公式高解析度裁切提取為圖片。

## 🌟 核心功能

*   **PDF 轉 Word (動態去邊界)**：智慧偵測每一頁的頁首/頁尾邊界，自動裁除頁碼與干擾資訊，產出排版乾淨的 .docx。
*   **AI 數學公式萃取 (Pix2Text MFD)**：透過深度學習物件偵測模型，精準定位 PDF 中的獨立公式 (Display Math)，並將其裁切為高解析度圖片。
*   **資源保護機制 (Guardrails)**：具備動態 DPI 降級、分批處理 (Batching + GC)、頁數上限防呆，保證處理數百頁的原文書籍時不發生記憶體溢出 (OOM)。
*   **自動產物打包**：每次轉檔與提取任務結束後，會自動將 Word 檔與公式圖片的 ZIP 壓縮包統合至獨立的時間戳記資料夾。

## 📂 資料夾架構

`	ext
📁 Project Root
├── config/                 # ⚙️ 全域設定與環境變數 (支援 .env 覆寫)
├── src/                    # 🧠 核心業務邏輯
│   ├── core_agent.py       # 主程式 Pipeline (包含 Tkinter 介面與批次邏輯)
│   ├── extraction/         # AI 公式萃取引擎 (MFD, OpenCV 裁切)
│   └── post_processing/    # 影像後處理工具
├── scripts/                # 🚀 啟動入口
│   └── run.py              # Tkinter GUI 與 CLI 啟動點
├── data/                   # 📦 資料與產出 (未受版本控制)
│   ├── 01_input/           # 預設的 PDF 來源資料夾
│   ├── 02_intermediate/    # 暫存檔與預覽圖
│   └── 03_output/          # 最終打包的 ZIP 與 DOCX
├── requirements.txt        # 依賴套件清單
├── .env.example            # 環境變數範本
└── run_extract.bat         # Windows 一鍵啟動腳本
`

## 🛠️ 安裝與啟動

### 1. 安裝環境
請確保安裝了 Python 3.9+，然後執行：
`ash
pip install -r requirements.txt
`
*(若有 GPU，強烈建議安裝 PyTorch 支援 CUDA 版本以加速 Pix2Text)*

### 2. 環境變數設定 (選用)
複製 .env.example 為 .env，可在此調整各項硬體保護限制與 API Key（如適用）：
`env
MAX_SAFE_PAGES=300
BATCH_SIZE=50
MAX_IMAGE_WIDTH=4000
FORMULA_DPI=300
`

### 3. 啟動程式
**Windows 使用者**：
直接點擊專案目錄下的 
un_extract.bat 即可啟動視覺化介面。

**命令列啟動**：
`ash
python scripts/run.py
`

### 4. 啟動 Web 介面 (最新版)
**Windows 使用者**：
直接點擊專案根目錄下的 
un_web.bat 即可啟動 FastAPI 伺服器。
啟動後請開啟瀏覽器前往：[http://127.0.0.1:8000](http://127.0.0.1:8000)

## 📅 更新日誌 (Changelog)
* **2026-08-29**: 新增 Web 介面 (FastAPI + 原生前端)
  * ✨ 支援拖曳上傳與短輪詢即時進度條。
  * 🎚️ **新增視覺化裁切預覽**：上傳 PDF 後，提供動態滑桿可即時預覽頁首/頁尾裁切邊界。
  * 🛡️ **CMYK 圖片崩潰修復**：核心引擎新增 Monkey Patch，自動將特殊印刷色彩轉碼為 RGB，徹底解決底層 pdf2docx 轉檔中斷的問題。
