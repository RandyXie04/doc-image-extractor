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

## 主要腳本

| 腳本 | 說明 |
|------|------|
| `pdf_engine_dispatcher.py` | 雙引擎排程與派發 |
| `process_ocr.py` | Surya OCR 版面分析與辨識（支援 `--no_footnote`） |
| `book_layout_extractor.py` | 版面結構提取（支援 `enable_footnotes=False`） |
| `md_to_docx.py` | Markdown 轉 Word |
