# Book PDF Digitalization Toolbox

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-CUDA%20%2F%20DirectML-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20LAN%20Server-0078D6?logo=windows&logoColor=white)](https://microsoft.com)

書籍 PDF 數位化工具箱是一套專為繁體中文出版、學術教材與歷史書籍數位化打造的全流程排版轉檔系統。採用 **FastAPI APIRouter 模組化後端 + 響應式幾何線條 Web 前端 + Schema-Driven TypeScript 雙向強型別契約層** 架構，支援本機獨立運算與企業內部網路（LAN）私有化集中部署。

---

## 介面特色與設計理念

- **預設淺色模式 (Default Light Mode)**：針對長時間校對書籍與審閱排版的編輯工作者量身設計，提供高清晰度、低視覺疲勞的紙本質感底色；支援右上角一鍵平滑切換深色主題。
- **極簡幾何線條視覺 (Clean Line Aesthetic)**：全面剔除裝飾性 Emoji 與多餘視覺噪音，統一採用 24×24 像素簡約 SVG 線條圖標與無襯線排版體系。
- **雙角色作業視角 (Dual User Profiles)**：
  - **出版社編輯模式 (Editor Mode)**：預設工作模式，隱藏技術底層細節，專注於檔案拖曳、四向邊界滑桿即時預覽、Word 樣式範本套用與原生視窗另存新檔。
  - **工程師除錯模式 (Developer Mode)**：提供 GPU 硬體探測診斷、詳細轉檔進度條、字型編碼分析表、Markdown 大綱階層樹狀編輯器與系統日誌。
- **自適應視口與響應式排版 (Responsive Viewport)**：
  - 劃分 4 級斷點（Mobile, Tablet, Desktop, Ultrawide），流體寬度消除寬螢幕右側留白。
  - 平板與行動裝置支援抽屜式折疊側邊欄（Off-canvas Drawer）、磨砂遮罩層與漢堡導覽選單。
- **原生作業系統整合 (Native OS Integration)**：伺服器支援調用 Windows 原生檔案選擇與另存新檔對話框，非阻塞管理視窗層疊（Z-order），轉檔完成後可一鍵於 Windows 檔案總管定位檔案。

---

## 核心工作流與模組體系

系統劃分為「兩大核心工作流」與「三大專屬輔助工具」：

### 核心工作流 (Primary Workflows)

| 工作流名稱 | 核心技術 | 適用場景與功能說明 | 專屬文件 |
| :--- | :--- | :--- | :--- |
| **全自動整稿 (OCR Pipeline)** | PyMuPDF + Surya OCR + 2D 座標三線表重建 + Pandoc | 原稿 PDF 初稿快速轉檔；向量 PDF 幾何文字流抽取；掃描書深度 OCR；四向視覺裁切代替啟發式頁眉刪除；預設無腳注雙通道；圖片目錄命名空間隔離。 | [說明文件](src/scripts/README_OCR.md)<br>[操作手冊](docs/WORKFLOW_GUIDE.md#主流程一全自動整稿-ocr-pipeline) |
| **POD 智能整稿 (POD Studio)** | Exemplar Learner + Propagation Engine + DocxSerializer + PodValidator | 出版級 Print-On-Demand 高精度排版；4 層混合擴散（5% 人工精修範本 -> 85% 規則狀態機擴散 -> 10% VLM 局部修復）；原始 PDF 幾何上下文綁定與壓平數據原位升級 Word 三線表格。 | [設計決策](docs/DECISIONS.md#adr-007)<br>[操作手冊](docs/WORKFLOW_GUIDE.md#主流程二pod-整稿-pod-studio) |

### 專用輔助工具 (Dedicated Auxiliary Tools)

| 工具名稱 | 核心技術 | 適用場景與功能說明 | 專屬文件 |
| :--- | :--- | :--- | :--- |
| **PDF 數學公式提取** | YOLOv8 ONNX + DirectML / CUDA / CPU | 專門識別繁複數理化公式，提供四向邊界裁切滑桿與預覽，避免邊界符號截斷，支援批次截圖導出 ZIP。 | [說明文件](src/README_MathFormula.md) |
| **文件圖片無損提取** | PyMuPDF Stream Extractor + OpenXML 活躍引用解析 | 自 PDF 物件流直接導出原始位元組（保留 CMYK/RGB/ICC Profile）；Word (.docx) 過濾歷史已刪孤立圖片；透明 PNG 灰階合成防黑底修復。 | [技術規格](docs/TECH_MODULES.md#3-文件圖片無損提取-image-extractor) |
| **方正書版亂碼修復** | Founder CMap & CID 映射庫 + Virtual Run Slicer | 針對早期方正書版（BDC/Founder）非標準字型與 CID 亂碼修復；切分腳註標記同時保留 Word OpenXML 粗體、斜體與字型設定。 | [說明文件](src/founder_tools/README_Founder.md) |

---

## 系統架構與關鍵技術

### 1. 雙引擎自適應調度 (Dual-Engine Dispatcher)
- **高速向量通道 (PyMuPDF)**：適用原生數位向量 PDF，直接讀取底層幾何文字流與字體度量資訊，毫秒級產出結構化文字，零錯字與形近字干擾。
- **深度辨識通道 (Surya OCR)**：適用圖書掃描件、雙層 PDF 或已轉曲字型，執行多語系文字偵測、版面區塊分割（Layout Analysis）與閱讀順序排序（Reading Order）。

### 2. 2D 座標三線表重建算子 (Three-Line Table Reconstructor, ADR-007)
- **純函數強型別契約**：以 `@dataclass(frozen=True)` 定義 `TextSpan2D`、`TableRegion` 與 `ReconstructedTable`。
- **三線表識別與分欄**：基於頁面頂部大線條、表頭底部分隔線與表尾大線條的 2D 幾何投影，自動定位表格區域並利用 Column X-Hints 切分跨欄文字。
- **跨列置中儲存格歸位**：解決多列群組儲存格因 `y0` 居中錯置至下排資料列的問題，自動上移歸位至該群組首列。
- **視覺裁切接管頁眉頁尾**：停用後端啟發式文字正則過濾（`strip_headers_heuristic: bool = False`），確保表頭單位符號（如 `ESR (mm/h)`）100% 完整保留。

### 3. 無腳注模式雙通道架構 (No-Footnote Architecture)
- **業務管線入口預設無腳注**（`no_footnote=True` / `enable_footnotes=False`）：徹底跳過註腳抽離判定，100% 保持內文連續流動，根治帶圈數字（①②③）、編號公式誤入頁底問題。
- **底層相容保障**：核心函式簽章保留預設參數以 100% 相容既有回歸測試套件。

### 4. POD 範本學習與批量樣式擴散 (POD Studio Pipeline)
- **黃金前導範本學習 (Golden Seed)**：由人工排版編輯精修前 1~2 個章節，`exemplar_learner.py` 自動提取樣式屬性、字型度量、自訂樣式名稱與三線表座標資訊。
- **零 API 成本狀態機擴散 (`propagation_engine.py`)**：將樣式規則批量擴散至全書切片語法樹（Section AST）。
- **原 PDF 幾何綁定與原位三線造表**：比對原 PDF 幾何座標，將未精修區段壓平的純文字數據段原位升級為標準 Word `Table Grid` (`w:tbl`)。
- **OpenXML 高精度序列化深模組 (`DocxSerializer`)**：封裝 python-docx 與 OpenXML 底層變更，保障 Pandoc 自訂樣式標記正確轉譯。
- **確定性驗收閘門 (`PodValidator`)**：執行字符守恆（Flowcheck）、語意標籤閉合與樣式白名單檢驗。

### 5. 全棧雙向強型別契約鐵籠 (Strict Schema-Driven Contracts, ADR-008 / ADR-009)
- **零裸字典原則 (Zero Raw-Dict Policy)**：全面使用 Pydantic v2 `ConfigDict(extra="forbid")` 定義請求、回應與版面契約（`schemas.py`、`contracts.py`），杜絕欄位名稱幻覺。
- **Schema-Driven TypeScript 代碼生成 (`generate_ts_contracts.py`)**：由後端 Schema 自動生成前端 TypeScript 契約定義（`frontend/src/types/contracts.ts`），離線環境免裝 Node.js 即可執行契約校驗與防漂移驗證（`--check`）。
- **型別安全 API 客戶端**：前端全面掛載 `podClient.ts`、`ocrClient.ts`、`formulaClient.ts` 與執行期守衛。

### 6. 模組化 APIRouter 與子行程檔案 IPC (ADR-009)
- **FastAPI APIRouter 領域拆分**：路由解耦為 `src/web/routers/pod_router.py`（POD 服務）與 `src/web/routers/system_router.py`（系統更新、硬體探測、方正修復、文件檢視器），核心應用 `app.py` 保持頂層符號相容。
- **檔案型 IPC 傳遞**：子行程命令列參數透過 `--style_mapping_file` 傳遞暫存 JSON 檔，避免 Windows 命令列引號跳脫截斷。
- **結構化進度白名單**：`is_meaningful_progress_line()` 過濾第三方套件雜訊（PyTorch/Surya/Pandoc warning），確保前端進度條穩定更新。

### 7. 每本書圖片命名空間隔離 (Per-Book Image Namespace Isolation, ADR-009)
- 當傳入書籍 `output_stem` 時，圖片自動隔離寫入 `data/03_output/images/{stem}/`，Markdown 產出相對路徑 `![](images/{stem}/...)`，杜絕多書連續或並行轉檔時的圖片覆寫碰撞。

### 8. 硬體加速與優雅降級 (Hardware Acceleration & Fallback)
- **ONNX Runtime DirectML**：公式識別通道優先掛載 DirectML，支援所有 DirectX 12 GPU（含 AMD, Intel, NVIDIA），無須配置 CUDA。
- **PyTorch CUDA 加速**：Surya OCR 偵測到 NVIDIA GPU 時自動配置 CUDA 與動態批次量；無 GPU 時平滑降級為多執行緒 CPU 運算。
- **動態狀態呈現**：側邊欄常駐硬體偵測指示器，即時顯示目前推論硬體狀態。

### 9. 隱私安全與 24 小時生命週期 (Privacy & Ephemeral Lifecycle)
- **零磁碟日誌政策**：伺服器不寫入永久性文本日誌。
- **24 小時定時銷毀**：背景 Janitor 自動安全銷毀超過 24 小時之暫存快取、中繼切片與產出檔案。
- **雙層上傳防禦**：結合 `MaxBodySizeMiddleware`（ASGI 標頭預檢）與 64KB 流式累加校驗，超額即刻中斷並清理磁碟殘留。

---

## 安裝指南

### 環境需求
- **作業系統**：Windows 10 / 11 (64-bit) 或 Windows Server
- **Python 版本**：Python 3.10 或以上版本
- **文字轉檔核心**：隨附於 `bin/pandoc.exe`，系統自動定位，無須手動配置環境變數。

### 安裝步驟

```bash
# 1. 複製專案庫
git clone https://github.com/RandyXie04/doc-image-extractor.git
cd doc-image-extractor

# 2. 建立並啟用虛擬環境 (建議)
python -m venv .venv
.venv\Scripts\activate

# 3. 安裝相依套件
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. 校驗 TypeScript 雙向型別契約 (可選)
python src/scripts/generate_ts_contracts.py --check
```

### AI 模型配置
模型檔案存放於根目錄 `models/`：
- **公式提取模型**：`models/yolo_v8_ft.onnx`
- **Surya OCR 模型**：初次執行時會自動自 Hugging Face 下載至本機快取；亦可執行 `python src/scripts/download_models.py` 進行預載。

---

## 啟動與操作

### 1. Windows 一鍵啟動 (推薦)
雙擊執行專案目錄下的啟動檔：
```bash
start_app.bat
```
系統將啟動背景服務並自動於預設瀏覽器（Edge / Chrome）開啟首頁 `http://127.0.0.1:8000`。

### 2. 開發與除錯模式
```bash
start_app_dev.bat
# 或命令列執行：
python main.py --dev
```
此模式將開啟詳細終端輸出、自動熱重載（Hot Reload）以及各節點暫存檔除錯檢視。

### 3. 自訂連接埠與伺服器常駐
```bash
# 指定 Port 且不自動彈出瀏覽器
python main.py --port 8080 --no-browser
```

---

## 區域網路集中部署 (LAN Private Deployment)

本專案支援免客戶端安裝的企業內網私有化部署：

```text
[辦公室 GPU 主機 / 轉檔伺服器] (執行 start_app.bat)
       │
       ├── http://192.168.1.100:8000
       │
       ├── 同仁 A 電腦 (瀏覽器操作全自動整稿，免裝 Python/模型)
       ├── 同仁 B 電腦 (瀏覽器操作 POD Studio 樣式擴散與原位三線造表)
       └── 編輯主管電腦 (線上即時預覽、校對與產出 Word/Markdown)
```

1. 在配備較佳算力的伺服器或主機上啟動服務，終端機會顯示區域網路 IP（例如 `http://192.168.1.100:8000`）。
2. 同一區域網路內的同仁，只需在瀏覽器輸入該 IP 即可直接使用全部轉檔功能。
3. 運算負載全由伺服器集中處理，結果文件直接於瀏覽器端下載，保護內部文件不外流至公有雲端。

---

## 專案目錄結構

```text
doc-image-extractor/
├── bin/                                # 內建二進位相依工具 (pandoc.exe)
├── config/                             # 系統設定 (settings.py, fonts.json, symbol_mapping.json)
├── data/                               # 運算資料目錄 (git-ignored, 24 小時自動清理)
│   ├── 01_input/                       # 上傳原始檔案 (PDF, DOCX)
│   ├── 02_intermediate/                # 中間運算暫存 (切片、預覽圖)
│   └── 03_output/                      # 轉檔產出物 (DOCX, Markdown, images/{stem}/)
├── docs/                               # 系統技術文件與架構規格
│   ├── ABOUT_LICENSE.md                # 系統授權與內網部署手冊
│   ├── BUG_LOG.md                      # 系統缺陷與修復追蹤日誌 (BUG-001 ~ BUG-010)
│   ├── DECISIONS.md                    # 架構設計決策記錄 (ADR-001 ~ ADR-010)
│   ├── RELEASE_SOP.md                  # 軟體發布標準作業程序
│   ├── TECH_MODULES.md                 # 核心模組技術規格
│   └── WORKFLOW_GUIDE.md               # 全流程操作手冊
├── frontend/                           # 前端 TypeScript 契約與響應式鷹架
│   ├── src/
│   │   ├── api/                        # 型別安全 API 客戶端 (podClient.ts, ocrClient.ts, formulaClient.ts)
│   │   ├── layout/                     # 視口狀態與響應式斷點 (useViewport.ts, ResponsiveShell.ts)
│   │   └── types/
│   │       └── contracts.ts            # Schema-Driven 自動生成 TypeScript 契約層
│   └── tsconfig.json                   # 嚴格 TypeScript 編譯設定 (checkJs, strict)
├── models/                             # AI 模型權重目錄 (YOLOv8 ONNX, Surya OCR)
├── src/
│   ├── core_agent.py                   # 核心控制器與轉檔管道協同器
│   ├── extraction/                     # 版面結構提取與強型別算子
│   │   ├── contracts.py                # Pydantic v2 版面契約 (LayoutRecordContract 等)
│   │   ├── post_processor.py           # Markdown 後處理與罕見字分析
│   │   ├── symbol_mapper.py            # 特殊符號與標點正規化映射
│   │   └── table_reconstructor.py     # 2D 幾何三線表重建純函數算子
│   ├── founder_tools/                  # 方正書版非標準編碼與 CMap 修復模組
│   ├── pod_studio/                     # POD 智能排版擴散工作流深模組
│   │   ├── blueprint_schema.py         # 排版藍圖結構定義
│   │   ├── docx_writer.py              # OpenXML 高精度序列化深模組 (DocxSerializer)
│   │   ├── exemplar_learner.py         # 人工精修範本特徵提取器
│   │   ├── pod_service.py              # POD 領域服務、原位三線造表與工作階段協同
│   │   ├── pod_validator.py            # 確定性驗收閘門 (字符守恆與樣式白名單)
│   │   ├── propagation_engine.py       # 零 API 成本規則擴散狀態機引擎
│   │   ├── section_ast.py              # 章節切片語法樹
│   │   ├── visual_fallback_repair.py   # VLM 多模態視覺局部修復
│   │   └── vlm_continuation_engine.py  # VLM 智慧續寫與版面補全
│   ├── scripts/                        # 獨立工具與轉換腳本
│   │   ├── book_layout_extractor.py    # 向量 PDF 幾何流結構解析
│   │   ├── extract_images.py           # 圖片批次無損提取
│   │   ├── generate_ts_contracts.py    # Pure-Python OpenAPI -> TypeScript 代碼生成器
│   │   ├── hardware_probe.py           # DirectML / CUDA / CPU 硬體偵測
│   │   ├── md_to_docx.py               # Markdown 轉 Word 排版核心
│   │   ├── model_manager.py            # AI 模型生命週期管理
│   │   ├── native_dialog.py            # Windows 原生對話框接口 (非阻塞置頂解除)
│   │   ├── pdf_engine_dispatcher.py    # 雙引擎分流排程器
│   │   ├── pdf_font_analyzer.py        # 內嵌字型掃描與度量計算
│   │   ├── pdf_image_extractor.py      # PDF 向量與點陣圖片分離
│   │   └── process_ocr.py              # Surya OCR 深度辨識與版面切分
│   ├── utils/                          # 通用工具庫 (file_guard, path_helper, task_queue)
│   └── web/                            # 網頁服務核心
│       ├── app.py                      # FastAPI 服務進入點與路由整合
│       ├── routers/                    # 領域拆分 APIRouter
│       │   ├── pod_router.py           # POD 智能整稿端點
│       │   └── system_router.py        # 系統設定、硬體探測、方正修復與文件檢視端點
│       ├── schemas.py                  # 全棧 API Pydantic v2 嚴格請求/回應模型
│       └── static/                     # 靜態前端資源
│           ├── extract_images.html     # 圖片無損提取介面
│           ├── formula.html            # 數學公式提取介面
│           ├── founder_repair.html     # 方正字型修復介面
│           ├── index.html              # 系統首頁與入口導覽
│           ├── ocr_pipeline.html       # 全自動整稿工作台
│           ├── pod_studio.html         # POD 智能整稿工作台
│           ├── js/                     # 前端核心腳本 (viewport_manager.js, output.js 等)
│           ├── sidebar.css             # 側邊欄與響應式主題樣式
│           └── sidebar.js              # 階層導覽、主題切換與文件 Modal 控制器
├── tests/                              # 完整單元與架構回歸測試套件 (150 項測試)
├── GLOSSARY.md                         # 系統關鍵名詞與領域術語表
├── main.py                             # 網頁服務核心啟動進入點
├── start_app.bat                       # 繁體中文 Windows 一鍵啟動批次檔
├── start_app_dev.bat                   # 開發與除錯環境啟動批次檔
├── requirements.txt                    # Python 模組相依清單
└── version.json                        # 軟體版本與更新識別檔
```

---

## 技術文件導覽 (Documentation Catalogue)

| 文件路徑 | 受眾分類 | 核心內容與指引 |
| :--- | :--- | :--- |
| [WORKFLOW_GUIDE.md](docs/WORKFLOW_GUIDE.md) | 編輯 / 開發者 | 全自動整稿、POD 人工預修擴散與輔助工具標準作業流程。 |
| [TECH_MODULES.md](docs/TECH_MODULES.md) | 開發者 | 雙引擎自適應 OCR、YOLOv8 DirectML 公式提取、無損圖片流與方正字型修復技術細節。 |
| [DECISIONS.md](docs/DECISIONS.md) | 開發者 | 架構設計決策記錄（ADR-001 ~ ADR-010），包含強型別契約、無腳注雙通道與三線表重建。 |
| [GLOSSARY.md](GLOSSARY.md) | 開發者 | 領域專有名詞與排版概念對照（Vector Pipeline, Section AST, DocxSerializer 等）。 |
| [BUG_LOG.md](docs/BUG_LOG.md) | 開發者 | 歷次系統缺陷根本原因分析（Root Cause）與修復驗證紀錄。 |
| [ABOUT_LICENSE.md](docs/ABOUT_LICENSE.md) | 編輯 / 開發者 | 系統授權、Surya OCR 非商用條款、Pandoc GPL 與內網私有部署合規指引。 |
| [RELEASE_SOP.md](docs/RELEASE_SOP.md) | 開發者 | 軟體版本發布與部署標準作業程序。 |
| [README_MathFormula.md](src/README_MathFormula.md) | 開發者 | PDF 數學公式提取模型訓練、ONNX 轉換與推論管線。 |
| [README_OCR.md](src/scripts/README_OCR.md) | 開發者 | 雙引擎 OCR 與圖文重排管線技術規格。 |
| [README_Founder.md](src/founder_tools/README_Founder.md) | 開發者 | 方正書版非標準編碼與 CMap 映射還原模組。 |

---

## 授權條款

本專案核心架構採用 [MIT License](LICENSE) 開源授權。
各子組件與模型具備獨立授權條款（包含 Surya OCR 深度辨識模型之 CC-BY-NC-SA 4.0 非商業限制與 Pandoc GPL 條款），詳細第三方合規指引請參見 [系統授權與內網部署手冊](docs/ABOUT_LICENSE.md)。
