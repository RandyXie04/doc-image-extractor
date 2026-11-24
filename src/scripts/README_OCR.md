# 雙引擎 PDF 轉檔與 OCR 管線

根據 PDF 類型自動選擇 PyMuPDF 向量解析或 Surya OCR 深度辨識，輸出 Markdown 並轉換為 Word。

## 功能

- **雙引擎分流** (`pdf_engine_dispatcher.py`)
  - PyMuPDF：原生文字型 PDF 直接提取文字流
  - Surya OCR：掃描書籍 / 純圖 / 轉曲 PDF 進行版面分析與辨識
  - 支援前端手動指定引擎或自動偵測
- **邊界裁切** -- 左右側裁切比例滑桿，裁除裝訂線黑邊與邊緣雜訊
- **即時進度** -- 後端進度端點 `/api/ocr_progress/{stem}`
- **標題偵測** (`HeadingDetector`) -- 結合字體大小、排版幾何與章節正則，對應 Markdown 標題層級
- **Word 樣式範本** -- 支援上傳自訂 `.docx` 範本，轉檔後可於介面調整段落階層並重新產出
- **Gemma 本機輔助判定** -- 若已安裝 Ollama `gemma4:e4b`，會協助覆核模糊的 PDF 斷行與標題候選；不改寫擷取文字，模型不可用時使用既有確定性流程。
- **DOCX 樣式建議預覽** -- 在「Word 樣式角色對應」按「Gemma 建議並預覽」，確認或調整角色樣式後再開始整稿。

`AI_LAYOUT_MODEL` 可指定文字判定模型，預設為 `gemma4:e4b`。本機尚未安裝時，工作台會顯示提示；請自行於 Ollama 安裝模型，整稿流程不會自動下載。

## 模型依賴與跨主機部署矩陣 (Model Deployment Matrix)

| 通道／節點 | 實際觸發模型 | 本機存放目錄 / 取得來源 | 備註 |
|---|---|---|---|
| **高速向量通道** (`book_layout_extractor.py`) | 無（純 PyMuPDF + 幾何演算法） | 不須下載模型 | 亦不依賴任何 `.pt` / `.onnx` |
| **圖片無損提取** (`extract_images.py`、`pdf_image_extractor.py`) | 無（純 PyMuPDF / OpenXML 串流解包） | 不須下載模型 | — |
| **Surya OCR Phase A：文字行偵測** (`process_ocr.py`) | [`vikp/surya_det3`](https://huggingface.co/vikp/surya_det3) (`EfficientViT`) | `models/surya_det3/`（由 `model_manager.py` 自 HF Hub 自動拉取） | 維持 PyTorch `.safetensors` |
| **Surya OCR Phase A：版面分析** (`process_ocr.py`) | [`datalab-to/surya_layout0`](https://huggingface.co/datalab-to/surya_layout0) (`surya-ocr>=0.7.0`) | `models/surya_layout0/`（由 `model_manager.py` 自 HF Hub 自動拉取） | 舊版 Segformer 權重會被 `is_legacy` 自動略過 |
| **Surya OCR Phase B：文字辨識** (`process_ocr.py`) | [`vikp/surya_rec2`](https://huggingface.co/vikp/surya_rec2) | `models/surya_rec2/`（與公式識別管線共用同一份） | 維持 PyTorch `.safetensors`，不轉 ONNX |
| **選用：模糊斷行／標題覆核** (`gemma_layout_assistant.py`) | Ollama `gemma4:e4b`（`AI_LAYOUT_MODEL`） | 本機 Ollama Registry（手動 `ollama pull gemma4:e4b`） | 不可用時自動跳過 |
| **選用：AI 楷體視覺辨識** (`ai_kaiti_classifier.py`) | Gemini Vision（`AI_KAITI_MODEL`）或本機 Ollama | `.env` 設定 `GEMINI_API_KEY` 或本機 Ollama | 需明確開啟 `--ai_kaiti` |

> **不使用之舊模型（可安全刪除）**：`surya_order`（已由 `sort_blocks_2d_reading_order` 幾何排序取代）、`surya_tablerec`（已由 `table_reconstructor.py` 三線表算子取代）及舊版 `models/surya_pt/` 巢狀目錄。

### HuggingFace 模型連結與拉取指令

所有 Surya OCR 權重統一採扁平目錄結構存放於專案根目錄的 `models/` 下：

- **文字行偵測 (`models/surya_det3/`)**：[https://huggingface.co/vikp/surya_det3](https://huggingface.co/vikp/surya_det3)
- **版面分析 (`models/surya_layout0/`)**：[https://huggingface.co/datalab-to/surya_layout0](https://huggingface.co/datalab-to/surya_layout0)
- **文字辨識 (`models/surya_rec2/`)**：[https://huggingface.co/vikp/surya_rec2](https://huggingface.co/vikp/surya_rec2)

> **啟動自動檢查**：直接執行 `start_app.bat` 啟動服務時，腳本會自動檢查 `models/` 下的必要模型（`models/pdf_extract_mfd.onnx`、`models/surya_det3/model.safetensors`、`models/surya_rec2/model.safetensors`、`models/surya_layout0/model.safetensors`），若有缺漏即自動設定 `PYTHONPATH` 並呼叫 `src/scripts/model_manager.py` 下載補齊；若需略過自動下載，可先設定環境變數 `SKIP_MODEL_DOWNLOAD=1`。

#### 方式一：一鍵自動下載全部必要模型（推薦）

```bash
# 於專案根目錄執行
python -m src.scripts.model_manager
```

#### 方式二：手動使用 `huggingface-cli` 逐一拉取

```bash
# 1. 文字行偵測 (Text-line detection -> models/surya_det3/)
huggingface-cli download vikp/surya_det3 --local-dir models/surya_det3

# 2. 版面分析 (Layout analysis -> models/surya_layout0/)
huggingface-cli download datalab-to/surya_layout0 --local-dir models/surya_layout0

# 3. 文字辨識 (Text recognition -> models/surya_rec2/，與公式提取管線共用)
huggingface-cli download vikp/surya_rec2 --local-dir models/surya_rec2
```

#### 方式三：使用 Python `huggingface_hub.snapshot_download`（與 `model_manager.py` 相同設定）

```python
from huggingface_hub import snapshot_download

SURYA_MODELS = {
    "models/surya_det3": "vikp/surya_det3",
    "models/surya_layout0": "datalab-to/surya_layout0",
    "models/surya_rec2": "vikp/surya_rec2",
}

for local_dir, repo_id in SURYA_MODELS.items():
    snapshot_download(
        repo_id=repo_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        ignore_patterns=["*.onnx", "*.safetensors.onnx", "*.msgpack"],
    )
```

## 主要腳本

| 腳本 | 說明 |
|------|------|
| `pdf_engine_dispatcher.py` | 雙引擎排程與派發 |
| `process_ocr.py` | Surya OCR 版面分析與辨識（支援 `--no_footnote`） |
| `book_layout_extractor.py` | 版面結構提取（支援 `enable_footnotes=False`） |
| `md_to_docx.py` | Markdown 轉 Word |
