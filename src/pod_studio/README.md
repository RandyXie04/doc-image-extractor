# POD 範本學習與智慧整稿工作台 (POD Studio)

採用四層混合工作流（Golden Seed 範本學習 + 狀態機規則擴散 + VLM 多模態局部修復／接續 + 確定性驗收閘門），將原始書籍生稿排版為出版社級別的 Print-On-Demand (POD) Word 文件。

## 各節點實際觸發模型對照

**本模組完全不讀取 `models/` 目錄下任何 YOLO 或 Surya 權重檔**，所有 AI 推論僅透過 `.env` 設定調度雲端 Gemini API 或本機 Ollama：

| 流程節點 | 對應模組 | 實際觸發模型與環境變數 | 失敗行為（Zero Silent Fallback） |
|---|---|---|---|
| **Golden Seed 範本學習** | `src/pod_studio/exemplar_learner.py` | 無（確定性 OpenXML 樣式抽取） | — |
| **單元切片 AST** | `src/pod_studio/section_ast.py` | 無（依章節邊界切分 Markdown） | — |
| **狀態機擴散引擎** | `src/pod_studio/propagation_engine.py` | 規則匹配為主；僅於開啟 LLM 輔助校正時呼叫 `GEMINI_MODEL`（預設 `gemini-3.5-flash-lite`）或本機 Ollama | 顯式記錄失敗狀態 |
| **VLM 局部截圖修復** | `src/pod_studio/visual_fallback_repair.py` | 依序讀取 `model` 參數 → `DEFAULT_AI_MODEL` → `GEMINI_MODEL`（預設 `gemini-3.8-flash`），非 Gemini 名稱則送本機 Ollama | 失敗直接拋出 `RuntimeError` |
| **VLM 視覺接續整稿** | `src/pod_studio/vlm_continuation_engine.py`、`src/pod_studio/pod_service.py` | 依序讀取前端指定模型 → `OLLAMA_MODEL` → `DEFAULT_AI_MODEL`（預設 `qwen3.5:4b`）；依名稱自動分流至 Gemini API 或本機 Ollama（`OLLAMA_HOST`） | 失敗直接拋出 `RuntimeError` |
| **確定性驗收閘門與 DOCX 編譯** | `src/pod_studio/pod_validator.py`、`src/pod_studio/docx_writer.py` | 無（字元守恆、徽標與樣式白名單檢核 + Pandoc/OpenXML 輸出） | 未達標直接阻斷交付 |

## 跨主機 `.env` 模型配置指南

1. **離線／本機推論（Ollama）**：
   - 於目標主機啟動 Ollama（預設 `OLLAMA_HOST=http://localhost:11434`），手動拉取視覺／文字模型：
     ```bash
     ollama pull qwen3.5:4b
     ```
   - 在 `.env` 設定 `OLLAMA_MODEL=qwen3.5:4b`、`OLLAMA_TEXT_MODEL=qwen3.5:4b`、`OLLAMA_NUM_CTX=16384`。
2. **雲端推論（Google Gemini API）**：
   - 在 `.env` 設定 `GEMINI_API_KEY` 與 `DEFAULT_AI_MODEL` / `GEMINI_MODEL`（例如 `gemini-3.8-flash`）。
