# 書籍 PDF 轉檔數位化工具箱 (Book PDF Digitalization Toolbox)

本專案是一個深度整合 **AI 數學公式識別 (YOLOv8)**、**文件圖片無損提取**、**方正書版亂碼修復** 以及 **全自動 OCR 與 Markdown/Word 排版** 的現代化自動化桌面工具箱。主要用於將大量技術書籍、學術 PDF、排版損壞的舊文件完美轉化為現代可編輯的 Word 格式。

## 🚀 核心功能

*   **🔍 1. PDF 數學公式提取 (含右界中文說明智慧納入與覆核標註)**：
    *   載入 YOLOv8 (ONNX) 模型精準定位獨立公式 (Display Math)。
    *   **智慧右界中文說明判定**：針對公式右側偶爾伴隨的條件說明（如 `(s_3 為正值時)`、`式中：...`、`（單位：米）` 等），系統**預設將其完整包入截圖**，確保數學語意不被生硬切斷。
    *   **人工覆核標註機制**：每次提取時，系統會自動在輸出目錄產出 `formula_right_boundary_chinese_review.txt`，逐一列出所有右界含有中文判定的公式編號、頁碼、座標與原文內容，方便人工快速覆核確認。
    *   提供互動預覽畫布調整邊界，自動將文件轉為圖文並茂的 Word 可編輯格式，並高解析度裁切獨立公式打包為 ZIP。
*   **🖼️ 2. 文件圖片無損提取**：支援批次拖曳 PDF 或 Word (DOCX) 檔案，自動提取最原始內嵌的高畫質圖片。支援自訂頁碼提取，並打包為 ZIP 壓縮檔。
*   **🛠️ 3. 方正書版亂碼修復**：針對早期方正排版系統 (Founder Bookmaker) 產生的 CMap 編碼缺陷，自動修復無法被正常選取或複製的亂碼、特殊字串與中英文標點符號。
*   **📄 4. 書籍 PDF 全自動 OCR 與排版**：基於 `RapidDoc`，針對被轉曲或掃描的 PDF，進行高精度版面分析、表格識別與中文 OCR 辨識。自動產出語意化 Markdown 並透過 Pandoc 套用 `template.docx` 範本，精準還原多階標題與原生複雜表格！具備**智慧 Pipeline 任務對齊機制**，僅轉換當前 OCR 產出的檔案並自動封存舊檔，避免轉檔髒資料殘留。

## 📂 資料夾架構

```text
📦 Project Root
 ├── config/                 # ⚙️ 系統設定與開發環境規範 (settings.py, RULE.md)
 ├── src/                    # 🧠 核心業務邏輯
 │   ├── core_agent.py       # 公式提取、Word 轉檔與右界中文覆核引擎
 │   ├── founder_tools/      # 方正亂碼修復工具與樣式範本 (template.docx)
 │   ├── scripts/            # 核心腳本 (process_ocr.py, md_to_docx.py, yolo_onnx_utils.py)
 │   └── web/                # 🌐 FastAPI 後端與 WebView2 前端介面
 ├── data/                   # 📁 資料與產出物目錄 (已排除於 Git)
 │   ├── 01_input/           # 預設上傳暫存目錄
 │   ├── 02_intermediate/    # 轉檔過程快取
 │   ├── 03_output/          # 最終產出的 ZIP、DOCX 與覆核 TXT
 │   └── database_text/      # 待 OCR 的原始 PDF 與 Word 範本
 ├── scratch/                # 🗑️ 開發測試快取暫存區 (定時自動清理)
 ├── app_window.py           # 🚀 主程式入口 (WebView2 原生桌面視窗 + FastAPI)
 ├── build_app.spec          # 📦 PyInstaller 打包規格設定檔
 ├── build_exe.bat           # 🔨 一鍵打包為獨立 EXE 腳本
 ├── version.json            # 🏷️ 應用程式與模型雙軌版本規範
 ├── requirements.txt        # 核心依賴套件清單
 └── README.md               # 專案說明文件
```

## 🛠️ 安裝與啟動說明

### 1. 安裝環境與 Python 套件
請確保系統已安裝 Python 3.9+，執行以下指令安裝套件：
```bash
python -m pip install -r requirements.txt
```
*(若有 GPU，強烈建議安裝支援 CUDA 版本的 PyTorch 與 ONNXRuntime-GPU 以加速 AI 推論)*

### 2. Pandoc 自動支援 (OCR 必備)
本系統已內建自動配置機制。執行 OCR 管線時，`pypandoc` 會自動為您下載並配置 Pandoc 環境，無需手動額外安裝龐大的安裝包。

### 3. 下載 AI 模型 (本地執行必備)
本工具箱在完全離線的本地端運行，首次使用或手動部署時請確認以下模型：
*   **YOLOv8 權重**：請將訓練好的 ONNX 模型放置於專案要求之路徑 (用於公式提取)。
*   **RapidDoc 權重**：系統在首次執行 OCR 管線時，`rapid-doc` 套件會自動從 HuggingFace / ModelScope 下載 PP-OCRv6、PP-DocLayoutV3 等輕量化 ONNX 模型至本機快取資料夾中，請確保初次執行時有網路連線。

### 4. 啟動桌面應用程式 (WebView2)
**Windows 使用者**：
直接點擊專案目錄下的 `start_app.bat`，即可啟動背景 FastAPI 伺服器並自動彈出原生的 Windows WebView2 桌面視窗。

**手動命令列啟動**：
```bash
python app_window.py
```

## 📦 PyInstaller 獨立執行檔打包

若要將專案打包為免安裝的綠色發行版本（解耦程式本體與大型權重檔）：

1. **一鍵編譯**：
   直接點擊專案根目錄下的 `build_exe.bat`，或在命令列執行：
   ```bash
   cmd /c build_exe.bat
   ```
2. **產出結構**：
   編譯完成後，免安裝綠色程式將產出於 `dist/PDF_Toolkit/`：
   ```text
   dist/PDF_Toolkit/
   ├── PDF_Toolkit.exe     # 主程式本體 (約 22 MB)
   ├── _internal/          # 內嵌 Python 執行時與前端 UI 資源
   └── version.json        # 版本元數據
   ```
3. **發行結構**：
   只需將 `dist/PDF_Toolkit/` 提供給使用者，使用者在同級目錄建立 `models/` 與 `data/` 即可完全獨立離線運行。

## 💡 開發與整合筆記
- 專案程式腳本一律採用純英文 ASCII 編寫（中文一律使用註解），確保在任何 Windows 編碼 (cp950/UTF-8) 環境下絕不引發編碼衝突。
- `config/settings.py` 具備 `sys.frozen` 自動偵測：打包前錨定原始碼目錄，打包後自動錨定 `.exe` 所在目錄，檔案讀寫無縫銜接。
- 所有產出檔案與中繼檔案均保存在 `data/` 目錄中，可透過 `config/skills/clear-project-cache/SKILL.md` 指引快速清理。
