# 書籍 PDF 轉檔數位化工具箱 (Book PDF Digitalization Toolbox)

本專案是一個深度整合 **AI 數學公式識別 (YOLOv8)**、**文件圖片無損提取**、**方正書版亂碼修復** 以及 **智慧雙引擎 OCR 與 Markdown/Word 排版** 的現代化自動化桌面工具箱。專為出版社編輯與工程師打造，主要用於將大量技術書籍、學術 PDF、排版損壞的舊文件完美轉化為現代可編輯的 Word 格式。

---

## 🚀 工具模組導覽

為提供更清晰的模組架構，各項核心功能的詳細操作說明已歸類至對應的腳本目錄中，請點擊下方連結參閱詳細文件：

1. **[🔍 PDF 數學公式提取與核心流程](src/README_MathFormula.md)**
   包含高精度 YOLOv8 模型定位、智慧右界中文說明判定與互動式邊界調整畫布的說明。
2. **[⚡ 智慧雙引擎 PDF 轉檔與 OCR 管線](src/scripts/README_OCR.md)**
   包含 PyMuPDF 向量解析、RapidDoc 深度排版 OCR、即時進度條與幾何/語意標題偵測等詳細說明。
3. **[🖼️ 文件圖片無損提取](src/scripts/README_ImageExtractor.md)**
   包含批次拖曳 PDF/Word 檔案進行無損原始高畫質圖片提取的操作說明。
4. **[🛠️ 方正書版亂碼修復](src/founder_tools/README_Founder.md)**
   專門針對早期「方正書版」排版系統產生的亂碼與 CMap 編碼缺陷進行修復的工具文件。

*(註：本系統全面整合了 Windows 原生檔案儲存視窗，並內建 24 小時過期快取自動清理的安全維運機制。)*

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
