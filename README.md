# Book PDF Digitalization Toolbox (Web 版)

書籍 PDF 數位化工具箱，採用純網頁化服務架構 (FastAPI + 現代化 Web 前端)，整合 YOLOv8 公式識別、雙引擎 OCR 排版、文件圖片提取與方正書版亂碼修復。支援本機獨立運算與公司區域網路 (LAN) 私有化集中部署。

---

## 功能模組

| 模組 | 說明文件 |
| ------ | ---------- |
| PDF 數學公式提取 | [README_MathFormula.md](src/README_MathFormula.md) |
| 雙引擎 PDF 轉檔與 OCR 管線 | [README_OCR.md](src/scripts/README_OCR.md) |
| 文件圖片無損提取 | [README_ImageExtractor.md](src/scripts/README_ImageExtractor.md) |
| 方正書版亂碼修復 | [README_Founder.md](src/founder_tools/README_Founder.md) |

---

## 安裝與依賴

### Python 套件

需求：Python 3.10+

```bash
python -m pip install -r requirements.txt
```

### Pandoc（OCR 管線必備）

已內建於 `bin/pandoc.exe`，`pypandoc` 會自動調用，無需額外安裝。

### AI 模型

模型置於專案根目錄 `models/`：
- **YOLOv8**：`models/yolo_v8_ft.onnx`（公式提取）
- **Surya OCR**：初次執行時會自動偵測並下載至模型目錄。

### 硬體加速架構 (Hardware Acceleration)

本專案具備全通道自動硬體偵測與自適應調度（Graceful Fallback）架構：
- **公式提取通道**：採用 ONNX Runtime DirectML，支援全系列 DirectX 12 / NVIDIA GPU 高速推論。
- **OCR 雙通道**：整合 PyTorch CUDA 加速，偵測到 NVIDIA GPU 時自動開啟 CUDA 模式並提升批次處理量；無顯卡時自動平滑降級為 CPU 相容模式。
- **文字整稿通道**：PyMuPDF 原生 C++ 幾何流解析，毫秒級極速處理。

---

## 啟動方式

### 1. Windows 一鍵啟動 (推薦)

雙擊專案目錄下的批次檔：

```bash
start_app.bat
```
啟動後會自動開啟預設瀏覽器（Chrome / Edge）連至 `http://127.0.0.1:8000`。

### 2. 命令列啟動 (自訂監聽 IP / Port)

```bash
# 預設監聽 0.0.0.0:8000 (本機與區域網路同仁皆可連入)
python main.py

# 指定連接埠或關閉自動開啟瀏覽器 (適合伺服器/後台常駐)
python main.py --port 8080 --no-browser
```

### 3. 開發除錯模式

```bash
start_app_dev.bat
# 或
python main.py --dev
```

---

## 公司內網私有化部署 (LAN Deployment)

只需在公司內具備 GPU / 算力的主機執行 `start_app.bat` 或 `python main.py`：
1. 終端機會顯示您的區域網路 IP（例如 `http://192.168.1.163:8000`）。
2. 同仁在公司同個 Wi-Fi / 區域網路下，直接在瀏覽器輸入該 IP 即可開始轉檔。
3. 同仁無需安裝 Python 或模型，算力全部由伺服器集中運算，轉檔結果直接在瀏覽器下載。

---

## 資料夾架構

```text
Project Root
├── config/                     # 系統設定 (settings.py, fonts.json)
├── src/
│   ├── core_agent.py           # 公式提取、Word 轉檔引擎
│   ├── extraction/             # 自動化管線節點
│   │   ├── nodes/
│   │   └── pipeline/
│   ├── founder_tools/          # 方正書版修復工具
│   │   ├── core/
│   │   └── parsers/
│   ├── scripts/
│   │   ├── pdf_engine_dispatcher.py    # 雙引擎排程 (PyMuPDF / Surya)
│   │   ├── process_ocr.py             # Surya OCR 版面分析與辨識
│   │   ├── process_ocr_no_footnote.py # 無腳注模式 OCR
│   │   ├── book_layout_extractor.py   # 版面結構提取
│   │   ├── book_layout_extractor_no_footnote.py
│   │   ├── md_to_docx.py             # Markdown 轉 Word
│   │   ├── extract_images.py         # 圖片無損提取
│   │   ├── pdf_image_extractor.py    # PDF 圖片提取
│   │   ├── pdf_font_analyzer.py      # PDF 字型分析
│   │   ├── hardware_probe.py         # GPU 硬體探測
│   │   ├── model_manager.py          # 模型管理
│   │   ├── download_models.py        # HuggingFace 模型下載工具
│   │   ├── native_dialog.py          # Windows 原生對話框
│   │   ├── cleanup_scratch.py        # 暫存清理
│   │   ├── dictionary_post_processor.py  # 辭典後處理
│   │   ├── ocr_rare_char_corrector.py    # 罕字校正
│   │   └── yolo_onnx_utils.py        # YOLO ONNX 工具
│   ├── utils/
│   │   └── path_helper.py
│   └── web/
│       ├── app.py              # FastAPI 後端
│       └── static/             # 前端網頁資源 (HTML, CSS, JS)
├── bin/                        # 內建 Pandoc 執行檔
├── data/                       # 資料目錄 (git ignored)
│   ├── 01_input/
│   ├── 02_intermediate/
│   ├── 03_output/
│   └── database_text/
├── models/                     # AI 模型權重
├── docs/                       # 開發記錄與說明
├── logs/                       # 執行日誌
├── scratch/                    # 開發暫存 (自動清理)
├── main.py                     # 網頁服務核心入口 (FastAPI + Uvicorn)
├── start_app.bat               # 網頁服務啟動腳本
├── start_app_dev.bat           # 開發除錯模式啟動腳本
├── version.json                # 版本資訊
└── requirements.txt            # Python 依賴清單
```
