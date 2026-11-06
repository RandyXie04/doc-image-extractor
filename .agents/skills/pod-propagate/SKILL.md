---
name: pod-propagate
description: Publisher POD diffusion workflow: learn styles from human pre-processed docx, chunk into section AST, propagate rules, validate with CLI gatekeeper, and compile via Pandoc.
---

# POD Propagate: 出版社 POD 範本學習與批量擴散技能

當處理需要整稿成出版社標準 POD Word 檔的書籍時，利用「5% 人工精修範本 (Golden Seed) ＋ 85% 規則引擎高速擴散 ＋ 10% Agent/VLM 局部修復」的四層三明治工作流。

## 核心設計原則

1. **嚴禁直接修改 Word DOM (`.docx`)**：Agent 與腳本統一在 Extended Markdown (`::: {custom-style="..."}`) AST 層級操作，最後由 `src/scripts/md_to_docx.py` 呼叫 Pandoc 搭配 `template.docx` 編譯成 Word。
2. **切片工作區（Section AST Workspace）**：將全書切為獨立的單元檔案（`scratch/pod_workspace/sec_001.md` ~ `sec_XXX.md`），杜絕行號偏移與 Context 溢位。
3. **確定性驗收閘門（Completion Gatekeeper）**：任何改動必須通過 `pod_validator.py` 驗收（字數守恆、必備標籤、圈號連續性、樣式合法性）。

---

## 標準執行步驟 (CLI Workflow)

### 步驟 1：從人工範本提取排版藍圖 (Learn)

從編輯精修的前 1~2 章 `.docx` 自動萃取樣式表、標籤模式與 Few-Shot 對照樣本：

```bash
python -m src.pod_studio.exemplar_learner \
  --raw "data/03_output/Book_raw.docx" \
  --golden "data/01_input/Book_前處理.docx" \
  --output "data/03_output/book_blueprint.json" \
  --samples 3
```

### 步驟 2：全書 Markdown 切片為 Section AST (Slice)

將生稿 Markdown 分割為各單元獨立切片：

```bash
python -m src.pod_studio.section_ast \
  --split "data/03_output/Book_raw.md" \
  --out-dir "scratch/pod_workspace"
```

### 步驟 3：批量規則引擎擴散 (Batch Propagate)

執行純本地狀態機的高速轉換（< 3 秒，0 API 成本），自動補齊常規【用法】、【組成】與圈號分行：

```bash
python -m src.pod_studio.propagation_engine \
  --workspace "scratch/pod_workspace" \
  --blueprint "data/03_output/book_blueprint.json"
```

### 步驟 4：執行驗收閘門檢查 (Validate Gatekeeper)

驗證全書各單元是否符合字數守恆、必備標籤與排版樣式：

```bash
python -m src.pod_studio.pod_validator \
  --workspace "scratch/pod_workspace" \
  --blueprint "data/03_output/book_blueprint.json" \
  --template "data/database_text/template.docx"
```

### 步驟 5：異常單元局部修復 (Agent / VLM Fallback)

若 `pod_validator` 報告某些單元缺失標籤（例如因原書轉曲導致 OCR 漏字）：

- 僅需針對有問題的單一 `scratch/pod_workspace/sec_XXX.md` 進行修復。
- Agent 可讀取該檔案，參照 `book_blueprint.json` 中的 `few_shot_examples` 進行精準補正。
- 或呼叫 `src/pod_studio/visual_fallback_repair.py` 擷取該頁 150 DPI PDF 截圖送交多模態模型修復。

### 步驟 6：重組並編譯為 POD Word 成品 (Reassemble & Compile)

驗收通過後，將切片重新封裝為完整 Markdown 並透過 Pandoc 編譯為 Word：

```bash
python -m src.pod_studio.section_ast \
  --join "scratch/pod_workspace" \
  --output "data/03_output/Book_處理完成.md"

python src/scripts/md_to_docx.py \
  --files "data/03_output/Book_處理完成.md" \
  --template "data/database_text/template.docx"
```

編譯完成後，清理 `scratch/pod_workspace` 暫存切片。
