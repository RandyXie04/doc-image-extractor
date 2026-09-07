# 書籍 PDF 轉檔數位化工具箱 (Book PDF Digitalization Toolbox)

本專案是一個深度整合 **AI 數學公式識別 (YOLOv8)**、**文件圖片無損提取**、**方正書版亂碼修復** 以及 **全自動 OCR 與 Markdown/Word 排版** 的自動化桌面工具箱。主要用於將大量技術書籍、學術 PDF、排版損壞的舊文件完美轉化為現代可編輯的 Word 格式。

## 🚀 核心功能

*   **🔍 1. PDF 數學公式提取**：載入 YOLOv8 (ONNX) 模型精準定位數學公式 (Display Math)。提供互動預覽畫布調整邊界，自動將文件轉為圖文並茂的 Word 可編輯格式，並高解析度裁切獨立公式打包為 ZIP。
*   **🖼️ 2. 文件圖片無損提取**：支援批次拖曳 PDF 或 Word (DOCX) 檔案，自動提取最原始內嵌的高畫質圖片。支援自訂頁碼提取，並打包為 ZIP 壓縮檔。
*   **🛠️ 3. 方正書版亂碼修復**：針對早期方正排版系統 (Founder Bookmaker) 產生的 CMap 編碼缺陷，自動修復無法被正常選取或複製的亂碼、特殊字串與中英文標點符號。
*   **📄 4. 書籍 PDF 全自動 OCR 與排版**：基於 RapidDoc，針對被轉曲或掃描的 PDF，進行高精度版面分析、表格識別與中文 OCR 辨識。自動產出語意化 Markdown 並透過 Pandoc 套用 	emplate.docx 範本，精準還原多階標題與複雜原生表格！

## 📂 資料夾架構

`	ext
📦 Project Root
 ├── config/                 # ⚙️ 系統設定與開發環境規範 (settings.py)
 ├── src/                    # 🧠 核心業務邏輯
 │   ├── core_agent.py       # (舊) CLI 與公式提取管線
 │   ├── extraction/         # AI 偵測與影像處理核心
 │   ├── founder_tools/      # 方正亂碼修復工具群與樣式範本
 │   ├── scripts/            # OCR 批次與 Pandoc 排版腳本
 │   └── web/                # 🌐 FastAPI 與 WebUI 前端介面
 ├── data/                   # 📁 資料與產出物目錄 (不入 Git)
 │   ├── 01_input/           # 預設上傳暫存目錄
 │   ├── 02_intermediate/    # 轉檔過程快取
 │   ├── 03_output/          # 最終產出的 ZIP 與 DOCX
 │   └── database_text/      # 待 OCR 的原始 PDF 與 Word 範本 (template.docx)
 ├── scratch/                # 🗑️ 開發測試快取暫存區
 ├── app_window.py           # 🚀 主程式入口 (WebView2 桌面視窗 + FastAPI)
 ├── build_app.spec          # 📦 PyInstaller 打包規格設定檔
 ├── build_exe.bat           # 🔨 一鍵打包為獨立 EXE 腳本
 ├── version.json            # 🏷️ 應用程式與模型版本規格
 ├── requirements.txt        # 核心依賴套件清單
 └── README.md               # 專案說明文件
`

## 🛠️ 安裝與啟動說明

### 1. 安裝環境與 Python 套件
請確保系統已安裝 Python 3.9+，執行以下指令安裝套件：
`ash
python -m pip install -r requirements.txt
`
*(若有 GPU，強烈建議安裝支援 CUDA 版本的 PyTorch 與 ONNXRuntime-GPU 以加速 AI 推論)*

### 2. Pandoc 安裝 (OCR 必備)
若要使用「全自動 OCR 與排版管線」，系統需具備 Pandoc 以將 Markdown 轉換為包含原生表格的 Word：
*   **自動安裝**：執行 OCR 管線時，pypandoc 會自動為您下載並配置 Pandoc。
*   **手動安裝 (可選)**：執行專案根目錄下的 pandoc-3.11-windows-x86_64.msi 進行安裝。

### 3. 下載 AI 模型 (本地執行必備)
本工具箱在完全離線的本地端運行，首次使用或手動部署時請確認以下模型：
*   **YOLOv8 權重**：請將訓練好的 ONNX 模型放置於專案要求之路徑 (用於公式提取)。
*   **RapidDoc 權重**：系統在首次執行 OCR 管線時，
apid-doc 套件會自動從 HuggingFace / ModelScope 下載 PP-OCRv6、PP-DocLayoutV3 等輕量化 ONNX 模型至本機快取資料夾中，請確保初次執行時有網路連線。

### 4. 啟動桌面應用程式 (WebView2)
**Windows 使用者**：
直接點擊專案目錄下的 start_app.bat，即可啟動背景 FastAPI 伺服器並自動彈出原生的 Windows WebView2 桌面視窗。

**手動命令列啟動**：
`ash
python app_window.py
`

## 📦 PyInstaller 獨立執行檔打包

若要將專案打包為免安裝的綠色發行版本（解耦程式與 350MB 大型權重檔）：

1. **一鍵編譯**：
   直接點擊專案根目錄下的 uild_exe.bat，或在命令列執行：
   `ash
   cmd /c build_exe.bat
   `
2. **產出位置**：
   編譯完成後，免安裝綠色程式將產出於：
   `	ext
   dist/PDF_Toolkit/
   ├── PDF_Toolkit.exe     # 主程式本體 (約 22 MB)
   ├── _internal/          # 內建 Python 執行時與 Web 靜態資源
   └── version.json        # 版本元數據
   `
3. **發行結構**：
   只需將 dist/PDF_Toolkit/ 提供給使用者，使用者可在同級目錄建立 models/ 與 data/ 即可完全獨立離線運行。

## 💡 開發與整合筆記
- 專案程式碼一律採用純英文 ASCII 編寫（中文一律使用註解），確保在任何 Windows 編碼 (cp950/UTF-8) 環境下絕不引發編碼衝突。
- config/settings.py 具備 sys.frozen 自動偵測：打包前錨定原始碼目錄，打包後自動錨定 .exe 所在目錄，檔案讀寫無縫銜接。
- 所有產出檔案與中繼檔案均保存在 data/ 目錄中，可透過 config/skills/clear-project-cache/SKILL.md 指引快速清理。
