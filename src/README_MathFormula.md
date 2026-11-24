# PDF 數學公式提取與識別管線 (3-Stage Formula Extraction)

結合 YOLOv8l MFD (ONNX)、安全外擴裁切與 SuryaOCR 局部公式識別，將 PDF／影像中的數學公式轉錄為 **LaTeX**、**MathML XML** 與 **`imgsz=1600` 高清 PNG** 截圖。

## 三階段架構與對應模型

| 階段 | 核心模組 | 實際觸發模型 | 權重格式與來源 |
|---|---|---|---|
| **Stage 1：公式偵測** | `src/extraction/formula_detector.py` (`FormulaDetector`) | `models/pdf_extract_mfd.onnx`（YOLOv8l MFD，`imgsz=1280`，來源：[`opendatalab/PDF-Extract-Kit-1.0`](https://huggingface.co/opendatalab/PDF-Extract-Kit-1.0)） | ONNX（`CUDAExecutionProvider` → `DmlExecutionProvider` → CPU fallback） |
| **Stage 2：安全外擴與裁切** | `src/extraction/formula_cropper.py` (`FormulaCropper`) | 無（OpenCV / PIL 確定性裁切） | — |
| **Stage 3：局部公式識別** | `src/extraction/formula_recognizer.py` (`RecognitionPredictor`) | `models/surya_rec2/`（[`vikp/surya_rec2`](https://huggingface.co/vikp/surya_rec2)，`['_math', 'zh']`） | PyTorch `.safetensors`（CUDA `float16` → CPU `float32` fallback） |
| **多格式導出與整合** | `src/extraction/formula_exporter.py`、`src/extraction/formula_pipeline.py`、`src/web/routers/formula_router.py` | 無（`latex2mathml` + PyMuPDF 向量裁切） | — |

> **為何 `surya_rec2` 維持 `.safetensors` 而非轉為 ONNX**：`surya_rec2` 為三段式自回歸 Encoder-Decoder（`DonutSwin` + `SuryaOCRTextEncoder` + `SuryaOCRDecoder`），深度依賴 PyTorch Static KV-Cache（`_setup_cache`）與逐 token 解碼迴圈，維持原生 PyTorch 格式才可保留 SDPA／FP16 加速並相容 `surya.recognition.batch_recognition`。

## 核心功能

- **行內與獨立公式保留**：支援 `Class 0`（行內公式 `inline`）與 `Class 1`（獨立公式 `isolated`），採絕對最小尺寸門檻（`min_width=12.0`, `min_height=10.0`），避免短公式（如 `f(x)=ax+bx`）在密集文本中被比例寬度過濾。
- **Web UI 使用提醒**：網頁介面（`src/web/static/formula.html`）之 `extract_inline` 預設未勾選（`False`）；若需於網頁提取行內短公式，請勾選「**包含顯著行內公式 (Inline Math)**」。程式端呼叫 `FormulaExtractionPipeline` 預設為 `extract_inline=True`。
- **四向安全外擴與邊距過濾**：Stage 2 強制施加 3–5px 安全 Padding 避免切斷括號與上下標，並支援網頁畫布紅／藍／綠四向邊距預覽線過濾頁首／頁尾雜訊。
- **三格式打包交付**：ZIP 產物包含 `formulas.json`、`formulas.tex`、`latex/*.tex`、`mathml/*.xml` 與 `images/*.png`（支援 PDF 向量座標轉換後以 `imgsz=1600` 輸出）。

## 跨主機模型部署與 HuggingFace 拉取指令

GitHub 單檔上限為 100 MB，所有模型權重皆未納入 Git 追蹤，新主機啟動時可由 `start_app.bat` 或 `src/scripts/model_manager.py`（`ensure_model_ready()`）自動檢查並補齊（若欲略過自動下載，可設定環境變數 `SKIP_MODEL_DOWNLOAD=1`）：

1. **`models/pdf_extract_mfd.onnx`（約 167 MB，Stage 1 公式偵測，`imgsz=1280`）**：
   - **HuggingFace 原始權重來源**：[https://huggingface.co/opendatalab/PDF-Extract-Kit-1.0](https://huggingface.co/opendatalab/PDF-Extract-Kit-1.0)（檔案路徑：`models/MFD/YOLO/yolo_v8_ft.pt`）
   - 優先從專案 **GitHub Releases Assets** 下載 `pdf_extract_mfd.onnx`（並依 `version.json` 之 `model_hash` 執行 SHA256 校驗）。
   - 若 GitHub Release 尚未提供該檔案，自動呼叫 `src/scripts/export_mfd_onnx.py` 從 HuggingFace [`opendatalab/PDF-Extract-Kit-1.0`](https://huggingface.co/opendatalab/PDF-Extract-Kit-1.0) 下載 `models/MFD/YOLO/yolo_v8_ft.pt` 並於本機轉出 `imgsz=1280`（opset 17）的 `models/pdf_extract_mfd.onnx`。
2. **`models/surya_rec2/`（約 897 MB，Stage 3 局部公式識別）**：
   - **HuggingFace 官方來源**：[https://huggingface.co/vikp/surya_rec2](https://huggingface.co/vikp/surya_rec2)
   - 由 `src/scripts/model_manager.py` 自動透過 `huggingface_hub.snapshot_download` 從官方 [`vikp/surya_rec2`](https://huggingface.co/vikp/surya_rec2) 拉取至 `models/surya_rec2/`（若與 OCR 管線共存則共用同一份目錄）。

### 方式一：一鍵自動下載與轉檔（推薦）

```bash
# 於專案根目錄執行：自動檢查並補齊 models/pdf_extract_mfd.onnx 與 models/surya_rec2/（含其他 Surya OCR 權重）
python -m src.scripts.model_manager
```

> 直接執行根目錄的 `start_app.bat` 時亦會自動設定 `PYTHONPATH`、檢查 `models/` 下所有必要權重並呼叫 `src/scripts/model_manager.py` 補齊缺漏模型。

### 方式二：單獨下載 MFD 原始權重並轉出 `models/pdf_extract_mfd.onnx`

```bash
# 自動自 opendatalab/PDF-Extract-Kit-1.0 拉取 models/MFD/YOLO/yolo_v8_ft.pt、校驗 SHA256 並匯出 imgsz=1280 ONNX
python src/scripts/export_mfd_onnx.py

# 或先手動使用 huggingface-cli 拉取 .pt 權重再執行轉檔：
huggingface-cli download opendatalab/PDF-Extract-Kit-1.0 models/MFD/YOLO/yolo_v8_ft.pt --local-dir .
python src/scripts/export_mfd_onnx.py --weights models/MFD/YOLO/yolo_v8_ft.pt --output models/pdf_extract_mfd.onnx --imgsz 1280
```

### 方式三：手動拉取 Stage 3 `models/surya_rec2/`（`huggingface-cli` / Python）

```bash
huggingface-cli download vikp/surya_rec2 --local-dir models/surya_rec2
```

或使用 Python `huggingface_hub.snapshot_download`（與 `src/scripts/model_manager.py` 相同配置，略過不須使用的 `.onnx` / `.msgpack` 檔案）：

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="vikp/surya_rec2",
    local_dir="models/surya_rec2",
    local_dir_use_symlinks=False,
    ignore_patterns=["*.onnx", "*.safetensors.onnx", "*.msgpack"],
)
```
