# Book PDF Digitalization Toolbox

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PyTorch](https://img.shields.io/badge/PyTorch-CUDA%20%2F%20DirectML-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20LAN%20Server-0078D6?logo=windows&logoColor=white)](https://microsoft.com)

書籍 PDF 數位化工具箱是一套專為繁體中文出版、學術教材與歷史書籍數位化打造的全流程排版轉檔系統。採用 **FastAPI 後端 + 簡約幾何線條 Web 前端** 架構，具備本機獨立運算與企業內部網路（LAN）私有化集中部署能力。

---

## 介面特色與設計理念

- **預設淺色模式 (Default Light Mode)**：針對長時間校對書籍與審閱排版的編輯工作者量身設計，提供高清晰度、低視覺疲勞的紙本質感底色；支援右上角一鍵平滑切換深色主題。
- **極簡幾何線條視覺 (Clean Line Aesthetic)**：全面剔除裝飾性 Emoji 與多餘視覺噪音，統一採用 24×24 像素簡約 SVG 線條圖標與無襯線排版體系。
- **雙角色作業視角 (Dual User Profiles)**：
  - **出版社編輯模式 (Editor Mode)**：預設工作模式，隱藏技術底層細節，專注於檔案拖曳、四向邊界滑桿即時預覽、Word 樣式範本套用與原生視窗另存新檔。
  - **工程師除錯模式 (Developer Mode)**：提供 GPU 硬體探測診斷、詳細轉檔進度條、字型編碼分析表、Markdown 大綱階層樹狀編輯器與系統日誌。
- **原生作業系統整合 (Native OS Integration)**：伺服器支援調用 Windows 原生檔案選擇與另存新檔對話框，轉檔完成後可一鍵於 Windows 檔案總管中定位實體檔案。

---

## 四大核心模組

| 模組名稱 | 核心技術 | 適用場景與功能說明 | 專屬文件 |
| :--- | :--- | :--- | :--- |
| **PDF 數學公式提取** | YOLOv8 ONNX + DirectML | 專門識別繁複數理化公式，提供邊界裁切滑桿與預覽，支援批次截圖輸出。 | [說明文件](src/README_MathFormula.md) |
| **雙引擎 OCR 與圖文重排** | PyMuPDF + Surya OCR + Pandoc | 向量 PDF 秒級幾何流解析；掃描書深度中文辨識；支援無腳注雙通道與階層樣式對齊。 | [說明文件](src/scripts/README_OCR.md) |
| **文件圖片無損提取** | PyMuPDF Stream Extractor | 自 PDF 與 Word 文件中批次無損解析並抽離所有點陣圖與向量圖，保留原始色彩空間。 | [說明文件](docs/TECH_MODULES.md#3-文件圖片無損提取-image-extractor) |
| **方正書版亂碼修復** | Founder CMap & CID 映射庫 | 針對早期方正書版（BDC/Founder）排版轉出之 PDF 進行非標準字型與 CID 亂碼修復。 | [說明文件](src/founder_tools/README_Founder.md) |

---

## 系統架構與關鍵技術

### 1. 雙引擎自適應調度 (Dual-Engine Dispatcher)
- **高速提取通道 (PyMuPDF)**：適用原生向量數位 PDF，直接讀取底層幾何文字流與字體度量資訊，毫秒級產出結構化文字。
- **深度辨識通道 (Surya OCR)**：適用圖書掃描件、雙層 PDF 或已轉曲字型，執行多語系文字偵測、版面區塊分割（Layout Analysis）與閱讀順序排序（Reading Order）。

### 2. 無腳注模式雙通道架構 (No-Footnote Architecture)
為根治包含大量帶圈序號（①②③）、編號公式的書籍在 OCR 時將正文誤判為腳注標記之痛點，本專案依據架構決策執行完全解耦：
- **標準管線 (`process_ocr.py`, `book_layout_extractor.py`)**：具備完整的腳注偵測、尾注關聯與交叉引用分析。
- **無腳注參數模式 (`--no_footnote` / `enable_footnotes=False`)**：完全移除所有腳注判定邏輯，100% 保留內文完整流向，避免誤殺內文數字。前端提供即時切換開關。

### 3. 硬體加速與優雅降級 (Hardware Acceleration & Fallback)
- **ONNX Runtime DirectML**：公式識別通道支援所有支援 DirectX 12 之 GPU（含 AMD, Intel, NVIDIA），無須配置 CUDA 環境。
- **PyTorch CUDA 加速**：OCR 深度辨識通道於探測到可用 NVIDIA GPU 時自動掛載 CUDA 加速並放大推論批次量；若無 GPU 則平滑降級為多執行緒 CPU 運算。
- **動態狀態顯示**：側邊欄常駐硬體偵測指示器，即時呈現目前運算裝置（DirectML GPU / CUDA / CPU）。

---

## 安裝指南

### 環境需求
- **作業系統**：Windows 10 / 11 (64-bit) 或 Windows Server
- **Python 版本**：Python 3.10 或以上版本
- **文字轉檔核心**：已隨附於 `bin/pandoc.exe`，系統會自動定位，無需手動安裝。

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
```

### AI 模型準備
模型檔案統一存放於根目錄 `models/`：
- **公式提取模型**：`models/yolo_v8_ft.onnx`
- **Surya OCR 模型**：初次執行時會自動自 Hugging Face 下載至本機快取目錄；亦可執行 `python src/scripts/download_models.py` 進行預載。

---

## 啟動與操作

### 1. Windows 一鍵啟動 (推薦)
雙擊執行專案目錄下的啟動檔：
```bash
start_app.bat
```
系統會啟動背景服務並自動於預設瀏覽器（Edge / Chrome）開啟首頁 `http://127.0.0.1:8000`。

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

本專案支援免客戶端安裝的企業內網私有化部屬：

```
[辦公室 GPU 主機] (執行 start_app.bat)
       │
       ├── http://192.168.1.100:8000
       │
       ├── 同仁 A 電腦 (瀏覽器操作，免裝 Python/模型)
       ├── 同仁 B 電腦 (瀏覽器操作，免裝 Python/模型)
       └── 編輯主管電腦 (線上即時預覽與產出 Word/Markdown)
```

1. 在配備較佳算力的伺服器或主機上啟動服務，終端機會顯示區域網路 IP（例如 `http://192.168.1.100:8000`）。
2. 同一區域網路（Wi-Fi 或內網實體線）內的同仁，只需在瀏覽器輸入該 IP 即可直接使用全部轉檔功能。
3. 運算負載全由伺服器集中處理，結果文件直接於瀏覽器端下載，保護內部文件不外流至公有雲端。

---

## 專案目錄結構

```text
doc-image-extractor/
├── config/                     # 系統設定 (settings.py, fonts.json)
├── src/
│   ├── core_agent.py           # 核心控制器與轉檔管道協同器
│   ├── extraction/             # Markdown 後處理深模組 (post_processor.py)
│   ├── founder_tools/          # 方正書版非標準編碼與 CMap 修復模組
│   ├── scripts/
│   │   ├── pdf_engine_dispatcher.py    # 雙引擎分流排程器
│   │   ├── process_ocr.py              # Surya OCR 版面分析（支援 --no_footnote）
│   │   ├── book_layout_extractor.py    # 幾何流結構解析（支援 enable_footnotes=False）
│   │   ├── md_to_docx.py               # Markdown 轉換 DOCX 排版模組
│   │   ├── extract_images.py           # 圖片批次無損提取
│   │   ├── pdf_image_extractor.py      # PDF 向量與點陣圖片分離
│   │   ├── pdf_font_analyzer.py        # PDF 內嵌字體掃描與度量計算
│   │   ├── hardware_probe.py           # 顯示卡與推論硬體探測
│   │   ├── model_manager.py            # AI 模型生命週期管理
│   │   └── native_dialog.py            # Windows 原生對話框接口
│   ├── utils/
│   │   └── path_helper.py              # 跨平台絕對路徑統一轉換器
│   └── web/
│       ├── app.py                      # FastAPI 網頁服務端點與 API
│       └── static/                     # Web 前端資源 (HTML, CSS, JS)
│           ├── index.html              # 功能入口首頁
│           ├── ocr_pipeline.html       # 全自動 OCR 與排版管線介面
│           ├── formula.html            # 數學公式提取介面
│           ├── extract_images.html     # 圖片提取介面
│           ├── founder_repair.html     # 方正修復介面
│           ├── sidebar.css             # 側邊欄與全域色彩主題變數
│           └── sidebar.js              # 側邊欄控制器、硬體指示器與主題切換
├── bin/                                # 內建相依二進位工具 (Pandoc)
├── data/                               # 運算資料目錄 (git-ignored)
│   ├── 01_input/                       # 上傳原始檔
│   ├── 02_intermediate/                # 中間狀態產物 (預覽圖、切片)
│   └── 03_output/                      # 轉檔產出物 (DOCX, Markdown)
├── models/                             # AI 模型目錄
├── docs/                               # 專案設計決策與規格文件
├── main.py                             # 網頁服務核心啟動進入點
├── start_app.bat                       # 繁體中文 Windows 一鍵啟動批次檔
├── start_app_dev.bat                   # 開發與除錯環境啟動批次檔
├── version.json                        # 軟體版本與更新識別檔
└── requirements.txt                    # Python 模組相依清單
```

---

## 授權條款

本專案核心架構採用 [MIT License](LICENSE) 開源授權。
各子組件與模型具備獨立授權條款（包含 Surya OCR 深度辨識模型之 CC-BY-NC-SA 4.0 非商業限制與 Pandoc GPL 條款），詳細第三方合規指引請參見 [系統授權與內網部署手冊](docs/ABOUT_LICENSE.md)。
