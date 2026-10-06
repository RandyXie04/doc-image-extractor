# Book PDF Digitalization Toolbox

書籍 PDF 數位化桌面工具箱，整合 YOLOv8 公式識別、雙引擎 OCR 排版、文件圖片提取與方正書版亂碼修復。

---

## 功能模組

| 模組 | 說明文件 |
|------|----------|
| PDF 數學公式提取 | [README_MathFormula.md](src/README_MathFormula.md) |
| 雙引擎 PDF 轉檔與 OCR 管線 | [README_OCR.md](src/scripts/README_OCR.md) |
| 文件圖片無損提取 | [README_ImageExtractor.md](src/scripts/README_ImageExtractor.md) |
| 方正書版亂碼修復 | [README_Founder.md](src/founder_tools/README_Founder.md) |

---

## 安裝

### Python 套件

需求：Python 3.9+

```bash
python -m pip install -r requirements.txt
```

### Pandoc（OCR 管線必備）

已內建於 `bin/pandoc.exe`，`pypandoc` 會自動調用，無需額外安裝。

### AI 模型

- **YOLOv8**：將 ONNX 權重放置於 `models/` 目錄
- **Surya OCR**：首次執行時自動從 HuggingFace 下載，需網路連線

---

## 啟動

Windows 一鍵啟動：

```bash
start_app.bat
```

命令列啟動：

```bash
python app_window.py
```

除錯模式：

```bash
start_app_dev.bat
```

---

## 打包

一鍵打包為獨立執行檔：

```bash
cmd /c build_exe.bat
```

產出位於 `dist/PDF_Toolkit/`：

```text
dist/PDF_Toolkit/
├── PDF_Toolkit.exe
├── _internal/
└── version.json
```

發行時將 `dist/PDF_Toolkit/` 提供給使用者，於同級目錄建立 `models/` 與 `data/` 即可離線運行。

---

## 資料夾架構

```text
Project Root
├── config/                     # 系統設定 (settings.py)
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
│   │   ├── native_dialog.py          # Windows 原生對話框
│   │   ├── updater_service.py        # 線上更新
│   │   ├── cleanup_scratch.py        # 暫存清理
│   │   ├── dictionary_post_processor.py  # 辭典後處理
│   │   ├── ocr_rare_char_corrector.py    # 罕字校正
│   │   └── yolo_onnx_utils.py        # YOLO ONNX 工具
│   ├── utils/
│   │   └── path_helper.py
│   └── web/
│       ├── app.py              # FastAPI 後端
│       └── static/             # 前端靜態資源
├── bin/                        # 內建 Pandoc 執行檔
├── data/                       # 資料目錄 (git ignored)
│   ├── 01_input/
│   ├── 02_intermediate/
│   ├── 03_output/
│   └── database_text/
├── models/                     # AI 模型權重
├── docs/                       # 文件 (BUG_LOG, RELEASE_SOP)
├── logs/                       # 執行日誌
├── scratch/                    # 開發暫存 (自動清理)
├── app_window.py               # 主程式入口 (WebView2 + FastAPI)
├── start_app.bat               # 啟動腳本
├── start_app_dev.bat           # 除錯模式啟動
├── build_app.spec              # PyInstaller 規格檔
├── build_exe.bat               # 打包腳本
├── updater.bat                 # 熱更新腳本
├── setup_pipeline.py           # 管線設定
├── download_models.py          # 模型下載
├── version.json                # 版本資訊
└── requirements.txt            # 依賴清單
```
