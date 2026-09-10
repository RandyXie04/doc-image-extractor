# 書籍 PDF 轉檔數位化工具箱 (Book PDF Digitalization Toolbox)

本專案是一個深度整合 **AI 數學公式識別 (YOLOv8)**、**文件圖片無損提取**、**方正書版亂碼修復** 以及 **智慧雙引擎 OCR 與 Markdown/Word 排版** 的現代化自動化桌面工具箱。專為出版社編輯與工程師打造，主要用於將大量技術書籍、學術 PDF、排版損壞的舊文件完美轉化為現代可編輯的 Word 格式。

---

## 🚀 核心功能

### 🔍 1. PDF 數學公式提取 (含右界中文說明智慧納入與覆核標註)
*   **高精度 YOLOv8 模型定位**：載入 YOLOv8 (ONNX) 模型精準定位獨立公式 (Display Math)。
*   **智慧右界中文說明判定**：針對公式右側偶爾伴隨的條件說明（如 `(s_3 為正值時)`、`式中：...`、`（單位：米）` 等），系統**預設將其完整包入截圖**，確保數學語意不被生硬切斷。
*   **人工覆核標註機制**：每次提取時，系統會自動在輸出目錄產出 `formula_right_boundary_chinese_review.txt`，逐一列出所有右界含有中文判定的公式編號、頁碼、座標與原文內容，方便人工快速覆核確認。
*   **互動式邊界調整畫布**：提供網頁畫布即時預覽與微調公式邊界，支援單頁公式預覽、快速排除雜訊區塊。

### ⚡ 2. 智慧雙引擎 PDF 轉檔與 OCR 管線 (Smart PDF Engine Dispatcher)
*   **智慧型雙引擎自動分流 (`pdf_engine_dispatcher.py`)**：
    *   **高速原生向量引擎 (PyMuPDF)**：自動採樣文件前段文字密度。若判定為原生文字型 PDF，直接切換高速文字流抽取，跳過耗時龐大的深度學習 OCR，速度提升 10 倍以上且記憶體極度輕量。
    *   **深度排版 OCR 引擎 (RapidDoc)**：若偵測為掃描書籍、純圖或轉曲 PDF，無縫切換至 RapidDoc 深度模型，精準進行版面分析、表格抽取與繁簡中文辨識。
    *   **UI 模式自選**：支援在前端下拉選單中手動強制指定「自動偵測」、「高速提取 (PyMuPDF)」或「深度識別 (RapidDoc)」。
*   **邊界裁切微調控制 (Margin Ratio Sliders)**：
    *   介面提供「左側裁切比例」與「右側裁切比例」滑桿，精準裁除書籍掃描時常見的裝訂線黑邊、陰影或邊緣雜訊。
*   **即時進度條與伺服器回報 (Real-time Progress Reporting)**：
    *   提供真實後端進度追蹤端點（`/api/ocr_progress/{stem}`），視覺化顯示分析進度百分比與即時狀態訊息。
*   **幾何與語意啟發式標題偵測 (`HeadingDetector`)**：
    *   結合字體大小、排版幾何特徵（置中對齊、單行字數、粗體、前後間距）與章節正則規則，將各級標題精準升級為 Markdown 語意（`#`、`##`、`###`）。
*   **自訂 Word 樣式範本與視覺化大綱編輯器 (Outline Editor)**：
    *   支援上傳自訂範本 (`.docx`) 進行樣式下拉對應，轉檔後於介面動態調整各段落階層（H1/H2/H3/內文），支援一鍵重新產出最終 Word 文件。

### 🖼️ 3. 文件圖片無損提取
*   支援批次拖曳 PDF 或 Word (DOCX) 檔案，自動提取最原始內嵌的高畫質圖片。
*   支援將彩色圖片批次轉換為灰階，並自動打包為 ZIP 壓縮檔。

### 🛠️ 4. 方正書版亂碼修復
*   針對早期方正排版系統 (Founder Bookmaker) 產生的 CMap 編碼缺陷，自動修復無法被正常選取或複製的亂碼、特殊字串與中英文標點符號。
*   支援上傳 PDF 或 DOCX 進行字體編碼修復與結構重組。

### 📁 5. Windows 原生檔案儲存與安全維運機制
*   **全功能 Windows 原生儲存對話框 (Native Save Dialog)**：
    *   所有功能模組（公式轉檔、OCR 轉檔、圖片擷取、方正修復）全面支援「📁 本機另存（原生視窗）」。
    *   點擊後直接彈出 Windows 檔案總管儲存視窗，讓使用者自行指定存放磁碟與路徑，徹底解決瀏覽器自動下載未提示路徑的痛點。
    *   **儲存結果與即時定位**：儲存完成後即時顯示綠色路徑提示卡，並附帶「📂 在 Windows 檔案總管中開啟」按鈕，可直接開啟資料夾並精準高亮該檔案 (`explorer /select`)。
    *   **安全防護與非同步架構**：採用非同步子進程 (`asyncio.create_subprocess_exec`) 呼叫對話框，避免阻塞 FastAPI Event Loop；實作嚴格路徑白名單校驗，防禦目錄遍歷 (Path Traversal / NIST PR.DS & ISO 27001)。
*   **24 小時過期快取自動清理 (Auto-cleanup Mechanism)**：
    *   系統內建伺服器生命週期防護，每次啟動時自動掃描輸出目錄，安全清除超過 24 小時之過期中繼檔，避免伺服器磁碟耗盡。
*   **雙運作模式（編輯專用 vs 工程師除錯）**：
    *   **出版社編輯模式（預設）**：極簡 UX 流程，隱藏技術日誌與內部暫存，產檔後直接彈出 Windows 原生「另存新檔」對話框。
    *   **工程師除錯模式**：解鎖完整即時轉檔 Log、內部資料夾開啟與各階段 ZIP 下載，可透過左側側邊欄按鈕切換或執行 `start_app_dev.bat` 啟動。

---

## 📂 資料夾架構

```text
📦 Project Root
 ├── config/                 # ⚙️ 系統設定與開發環境規範 (settings.py, RULE.md)
 ├── skills/                 # 📚 專案專用架構與開發技能規範 (python-pdf-workbench)
 ├── src/                    # 🧠 核心業務邏輯
 │   ├── core_agent.py       # 公式提取、Word 轉檔與右界中文覆核引擎
 │   ├── founder_tools/      # 樣式範本、標記偵測與啟發式標題偵測 (HeadingDetector)
 │   ├── scripts/            # 核心腳本工具集
 │   │   ├── pdf_engine_dispatcher.py  # ⚡ 智慧雙引擎排程器 (PyMuPDF vs RapidDoc)
 │   │   ├── native_dialog.py          # 📁 Windows 原生另存新檔對話框子程序
 │   │   ├── process_ocr.py            # 📄 RapidDoc 深度 OCR 版面分析
 │   │   ├── md_to_docx.py             # 📝 Markdown 轉換至 Word 格式
 │   │   ├── extract_images.py         # 🖼️ 文件圖片無損批次提取
 │   │   ├── hardware_probe.py         # 💻 GPU 硬體探測與 DirectML 自動配置
 │   │   └── updater_service.py        # 🔄 線上版本檢查與熱更新模組
 │   └── web/                # 🌐 FastAPI 後端與靜態網頁前端 (WebUI)
 ├── data/                   # 📁 資料與產出物目錄 (已排除於 Git)
 │   ├── 01_input/           # 預設上傳暫存目錄
 │   ├── 02_intermediate/    # 轉檔過程快取
 │   ├── 03_output/          # 最終產出的 ZIP、DOCX 與覆核 TXT (具 24h 自動清理)
 │   └── database_text/      # 待 OCR 的原始 PDF、系統/使用者自訂 Word 範本
 ├── scratch/                # 🗑️ 開發測試快取暫存區 (定時自動清理)
 ├── app_window.py           # 🚀 主程式入口 (WebView2 原生桌面視窗 + FastAPI)
 ├── start_app.bat           # 🏢 出版社編輯模式啟動腳本 (一鍵啟動)
 ├── start_app_dev.bat       # 🛠️ 工程師除錯模式啟動腳本
 ├── build_app.spec          # 📦 PyInstaller 打包規格設定檔
 ├── build_exe.bat           # 🔨 一鍵打包為獨立 EXE 腳本
 ├── updater.bat             # 🔄 背景自動熱更新替換批次腳本
 ├── version.json            # 🏷️ 應用程式與模型雙軌版本規範
 ├── requirements.txt        # 核心依賴套件清單
 └── README.md               # 專案說明文件
```

---

## 🛠️ 安裝與啟動說明

### 1. 安裝環境與 Python 套件
請確保系統已安裝 Python 3.9+，執行以下指令安裝基本套件：
```bash
python -m pip install -r requirements.txt
```

**💻 硬體自適應探測與 GPU 智慧加速佈署 (Adaptive Hardware Provisioning)**
本工具內建智慧硬體探測模組（針對 RTX 30/40/50 系列獨立顯卡）。啟動時將自動在背景偵測硬體環境：
- 若命中高效能 GPU 且具備網路連線，系統會**自動無痛安裝並切換至 `onnxruntime-directml` 加速引擎**。
- 若為無顯卡或無網路環境，將優雅降級維持純 CPU 模式運作，確保各種環境皆能順暢不卡死。
- 探測結果將快取於 `config/.hardware_profile.json`，後續啟動達到 **0 毫秒跳過探測** 的秒開體驗。

### 2. Pandoc 自動支援 (OCR 必備)
本系統已內建自動配置機制。執行 OCR 管線時，`pypandoc` 會自動為您下載並配置 Pandoc 環境，無需手動額外安裝龐大的安裝包。

### 3. 下載 AI 模型 (本地執行必備)
本工具箱在完全離線的本地端運行，首次使用或手動部署時請確認以下模型：
*   **YOLOv8 權重**：請將訓練好的 ONNX 模型放置於專案要求之路徑 (用於公式提取)。
*   **RapidDoc 權重**：系統在首次執行深度 OCR 管線時，`rapid-doc` 套件會自動從 HuggingFace / ModelScope 下載輕量化 ONNX 模型至本機快取資料夾中，請確保初次執行時有網路連線。若使用原生向量 PDF，則直接透過 PyMuPDF 解析，無需下載此模型。

### 4. 啟動桌面應用程式 (WebView2)
**Windows 使用者**：
直接點擊專案根目錄下的 `start_app.bat`，即可啟動背景 FastAPI 伺服器並自動彈出原生的 Windows WebView2 桌面視窗。

**手動命令列啟動**：
```bash
python app_window.py
```

---

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

---

## 💡 開發與整合筆記
- **字元編碼規範**：專案程式腳本一律採用純英文 ASCII 編寫（中文需求一律改以註解說明），確保在任何 Windows 編碼 (cp950 / UTF-8) 環境下絕不引發編碼衝突。
- **路徑防禦性設計**：`config/settings.py` 具備 `sys.frozen` 自動偵測：打包前錨定原始碼目錄，打包後自動錨定 `.exe` 所在目錄，檔案讀寫無縫銜接。
- **檔案隔離與生命週期管理**：所有暫存與產出物皆存放於 `data/` 與 `scratch/`，系統於啟動時自動清理逾 24 小時之產出物，嚴防磁碟佔滿風險。
