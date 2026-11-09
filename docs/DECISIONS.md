# Architectural Decision Records (DECISIONS.md)

本文件依據 `decision-log` 規範維護專案關鍵架構與設計決策紀錄（ADR）。

## 歷史決策索引（Historical ADRs referenced in `docs/BUG_LOG.md`）

- **ADR-003 — 字體審閱預設自動規則與雙通道章節標題擴充**：前端字體 Modal 預設改為 `auto`，擴充章節正則與 TOC 前導點過濾，並支援 Surya `surya_text`。
- **ADR-004 — 管線原子性與 Surya 0.6 模型對齊守則**：子程序失敗或目標檔案未實體生成時嚴禁回報 `progress: 100`，強制使用 Surya 0.6 官方模型架構。
- **ADR-005 — 特殊符號映射與 2D 卡片閱讀流守則**：建立 `symbol_mapping.json` 還原帶圈數字與括號，實作 2D 橫帶聚類排序，並在 Pandoc 停用 `subscript`（`-subscript`）。
- **ADR-006 — OCR 雙軌混合解析與圖文環繞段落合併架構**：優先映射原生向量文字層，對高度 `>35px` 區塊執行水平投影單行切片（`_slice_box_into_lines`），並支援圖文環繞斷行合併。

---

## ADR-007 — 雙通道 2D 座標三線表重建、視覺裁切取代頁眉啟發式刪除、管線預設無腳注與強型別算子契約

### Status

Accepted

### Context

在處理醫學與學術出版書籍（如《強直性脊柱炎》）時，既有架構暴露出五項系統性缺陷：

1. **三線表失明與首字框誤判**：PyMuPDF `page.find_tables()` 僅能偵測四邊封閉格線表，對無垂直線之標準學術三線表檢出率為 0%，卻將 35 個章節首字下沉裝飾框誤判為 `1x2` 表格；失去表格邊界後，跨列垂直置中的儲存格（如 `刺络埋线组 43`）因 `y0` 居中而穿插至錯誤資料列。
2. **雙重頁眉過濾誤殺表頭**：使用者已於前端透過紅藍綠四向裁切滑桿（`set_cropbox`）人工裁除頁眉頁尾，但後端 `book_layout_extractor.py` 仍執行硬編碼 `is_page_header()`（頂部 11% 且含 `/` 即刪除），導致位於頁面頂端的表格表頭（含 `ESR（mm / h）`）被整行抹除。
3. **特殊標記腳注誤傷內文編號**：出版社來稿無特殊標記注腳參照，預設開啟腳注偵測會導致頁底條列或表注被誤抽離。
4. **POD 通道缺乏原始 PDF 幾何上下文**：POD 階段一僅上傳預修 `.docx`，階段二無法得知後半部被壓平的純文字段落（如表 4）在原 PDF 中實為三線表。
5. **Python 裸 `dict` 引發跨模組欄位幻覺**：表格與版面區塊以無結構 `dict` 傳遞，容易在跨通道優化時產生鍵名不一致。

### Decision

1. **建立強型別純函數表格重建算子（`src/extraction/table_reconstructor.py`）**：
   - 採用 `@dataclass(frozen=True)` 定義 `TextSpan2D`、`TableRegion`、`ReconstructedTable`，禁止裸 `dict` 跨函式傳遞。
   - 實作 `is_valid_pymupdf_table()` 濾除窄小首字下沉假表格（寬度 `< 0.25 * page_w` 且字數 `<= 6`）。
   - 實作 `detect_three_line_table_regions()` 與 `reconstruct_table_from_2d_spans()`：利用水平線段群組與分段點（Column X-Hints）切分欄位，並將跨列垂直置中的左側群組儲存格自動上移歸位至該群組首列。
2. **頁眉頁尾 100% 交由前端視覺裁切控制**：
   - `_parse_pdf_layout_flow()` 預設設定 `strip_headers_heuristic: bool = False`，停用後端 `is_page_header()` / `is_page_footer()` 文字正則刪除。
3. **業務管線入口預設無腳注模式（兼顧底層測試相容）**：
   - 在 `ocr_pipeline.html`、`app.py`、`pdf_engine_dispatcher.py` 與 `pod_service.py` 全面預設 `no_footnote=True`（即 `enable_footnotes=False`）；同時保留底層函式 `process_book_vector_pdf` 與 `process_page_footnotes` 的簽章預設值 `True` 以維持既有單元測試（`test_p1_refactoring.py`）100% 相容。
4. **整數空白節標題識別與行尾黏連切段**：
   - 支援 `^\d+[\s\u3000]+[\u4e00-\u9fff]{2,15}$` 節標題識別，並在句末黏連時（如 `...。 4 讨论`）自動切分為獨立標題段落。
5. **POD 階段一新增原 PDF 上傳格與階段二原位造表**：
   - `pod_studio.html` 階段一雙欄並排接收「人工預修範本 (`.docx`)」與「原始 PDF (`.pdf`)」，於 `/api/pod/2_compile_blueprint` 建立含三線表結構之 `Book_raw_ast.json`。
   - `pod_service.py` 在階段二 `propagate_and_validate_session()` 自動定位 `last_modified_idx` 之後的表題段落，將下方壓平的純文字數據段原位替換為真實 Word `Table Grid` (`w:tbl`) 表格。

### Alternatives

- **替代方案 A**：調高 PyMuPDF `find_tables(strategy="text")` 敏感度。實測該策略對《強直性脊柱炎》P.156~160 仍回傳 0 個表格，且會在普通正文產生大量假表格。
- **替代方案 B**：直接修改底層函式簽章 `enable_footnotes: bool = False`。這會破壞既有 `tests/test_p1_refactoring.py` 的簽章反射測試；在業務調用層（UI/API/Dispatcher/POD）預設關閉更為穩健。

### Consequences

- 向量通道與純 OCR 通道共用同一套 2D 表格重建算子，三線表及頂部含 `/` 單位之表頭可 100% 完整保留並轉為 Word `Table Grid`。
- POD 通道可在不重新執行全書初稿轉檔的情況下，直接透過階段一綁定之原 PDF 將未精修區段的殘缺文字表升級為真實 Word 表格。
- 嚴格遵守 `test_vector_ast.py` 的 Zero-Disk-IO、檔案控制代碼釋放與 Golden SHA-256 基準。

### Related Bug

BUG-007

---

## ADR-008 — P2 雙向強型別契約鐵籠與 Schema-Driven TypeScript 自動生成架構

### Status

Accepted

### Context

前端 HTML/JS 與後端 Python 之間若缺乏編譯期與執行期雙向型別契約，且內部以鬆散 `dict[str, Any]` 傳遞版面結構（如 `layout_records`），Agent 在跨端優化演算法時極易產生欄位名稱幻覺（Key Hallucination）或靜默漏欄。此外，Windows 離線執行環境未必安裝 Node.js，型別生成工具不可強依賴外部 `npm` 才能產出契約。

### Decision

1. **鐵律一（Zero Raw-Dict Policy）**：
   - 新增 [`src/extraction/contracts.py`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/extraction/contracts.py) 與 [`src/web/schemas.py`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/web/schemas.py)，統一開啟 `ConfigDict(extra="forbid")`，任何未定義欄位立即觸發 `ValidationError`。
2. **鐵律二（Schema-Driven Pure-Python OpenAPI -> TypeScript Codegen）**：
   - 新增 [`src/scripts/generate_ts_contracts.py`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/scripts/generate_ts_contracts.py)，直接反射 Pydantic v2 JSON Schema 自動生成 [`frontend/src/types/contracts.ts`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/frontend/src/types/contracts.ts)（含可辨識聯合型別 `PropagationPayload`、`LayoutRecordContract`、`PodSessionPhase`），並支援 `--check` 防漂移校驗。
3. **鐵律三（TypeScript 前端狀態機與雙重靜態校驗閘門）**：
   - 建立 [`frontend/src/api/podClient.ts`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/frontend/src/api/podClient.ts) 與瀏覽器原生 ES 模組 [`src/web/static/js/pod_contracts.js`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/web/static/js/pod_contracts.js)，透過 `pyright` + `pytest tests/test_p2_strict_contracts.py` 執行零誤差契約檢驗。

### Consequences

- 演算法算子輸出之 `layout_records`（如 `TableLayoutContract` 新增 `caption_text`）若未同步宣告於契約中，單元測試將立即攔截。
- 即使在無 Node.js 的純 Python 部署環境，仍可 100% 自動生成與校驗 TypeScript 契約定義。

---

## ADR-009 — P3 全棧強型別契約擴展（P2-A~P2-D）、每本書圖片命名空間隔離、子行程 JSON 檔案傳遞與 FastAPI `APIRouter` 模組化

### Status

Accepted

### Context

完成 P2 基礎建設後，審計發現專案仍存在四個未納管之前端工作台（`ocr_pipeline`、`pod_studio` VLM、`formula`、`extract_images`/`founder_repair`）與五項潛在架構風險：

1. `process_ocr.py`（22 項）與 `core_agent.py`（6 項）存在 `pyright` 靜態型別錯誤，且純 OCR 區塊尚未強制執行 `LayoutRecordContract` 驗證。
2. `book_layout_extractor.py` 與 `process_ocr.py` 共用扁平 `data/03_output/images/` 目錄，不同書籍之同頁圖片（如 `image_p1_0.png`）會互相覆寫。
3. `app.py` 以 CLI 原始字串傳遞 `--style_mapping` 並在讀取 `stdout` 時未過濾第三方套件警告（`UserWarning`/`FutureWarning`），易污染前端進度文字。
4. `src/web/app.py` 單檔超過 1,700 行，路由職責高度耦合，不利於長期維護與 Agent 精準閱讀。

### Decision

1. **全量核心腳本零靜態錯誤（Zero Pyright Errors）與純 OCR 契約對齊**：
   - 修正 `process_ocr.py` 與 `core_agent.py` 所有未綁定變數與型別不匹配問題，並於 `process_ocr.py` 實作 `build_ocr_layout_contracts()`，確保純 OCR 通道輸出之段落、標題、表格、圖片、腳注均通過 `validate_layout_records()` 嚴格校驗。
2. **每本書圖片目錄命名空間隔離（Per-Book Image Namespace Isolation）**：
   - 當指定 `output_stem`（或 `isolate_images_by_stem=True`）時，將圖片提取目錄隔離至 `data/03_output/images/{stem}/`，Markdown 相對路徑輸出為 `![](images/{stem}/image_p{page}_{idx}.png)`；同時保留未傳入 `output_stem` 時之預設 `images/` 行為以 100% 相容既有單元測試。
3. **檔案型子行程 IPC 與結構化進度過濾**：
   - 在 `pdf_engine_dispatcher.py` 與 `process_ocr.py` 新增 `--style_mapping_file` 參數，由 `app.py` 將 `style_mapping` 寫入任務專屬暫存 JSON 檔傳遞並於 `finally` 自動清理。
   - 新增 `is_meaningful_progress_line()` 過濾子行程非 JSON 輸出，攔截 `Traceback`、`UserWarning`、`site-packages` 等第三方雜訊。
4. **P2-A ~ P2-D 契約擴展與 FastAPI `APIRouter` 領域拆分**：
   - 擴充 `src/web/schemas.py` 與 `generate_ts_contracts.py`，自動生成涵蓋自動整稿、字體審閱、POD VLM 接續、公式擷取、方正修復與硬體狀態之 `frontend/src/types/contracts.ts`，以及 `ocrClient.ts`、`formulaClient.ts` 與 `ocr_contracts.js`。
   - 將 POD 智慧整稿路由與系統/硬體/方正修復路由分別抽離至 `src/web/routers/pod_router.py` 與 `src/web/routers/system_router.py`，並在 `src/web/app.py` 透過 `app.include_router()` 掛載且保留原函式符號匯出。

### Consequences

- 消除多書並行或連續轉檔時的圖片覆寫風險，且 Pandoc `--resource-path` 無需修改即可自動解析 `images/{stem}/` 下的圖片。
- `src/web/app.py` 大幅瘦身約 400 行，同時 100% 保持對既有測試中 `monkeypatch.setattr(web_app.PATHS, ...)` 與直接匯入函式的向下相容性。

### Related Bug

BUG-008

---

## ADR-011 — 零靜默降級政策（Zero Silent Fallback）與啟動批次 Ollama 自動伺服守護架構

### Status

Accepted

### Context

在 POD 數位整稿通道中，當使用者選取本機離線模型（如 `qwen3.5:4b`）進行樣式分類時，若本機 Ollama 服務尚未啟動或尚未下載該模型，舊版程式碼會靜默降級嘗試調用雲端 Gemini API，並錯誤地將本機模型名稱傳遞至 Gemini 端點，引發 `404 NOT_FOUND: models/qwen3.5:4b is not found for API version v1beta`。
此外，使用者在啟動 `start_app.bat` 或 `start_app_dev.bat` 時缺乏自動檢測與啟動 Ollama 服務機制，且本機未下載指定模型時缺乏明確前端錯誤通知。

### Decision

1. **零靜默降級政策（Zero Silent Fallback）**：
   - 嚴格禁止跨廠商或跨服務靜默 Fallback。選定本機離線模型時，若 Ollama 未連線或未安裝該模型，立即中斷並拋出明確的 `RuntimeError`，提示使用者服務未啟動或模型未安裝，禁止私自降級調用雲端 API；同理，選取 Gemini 雲端模型時若無金鑰亦立即拒絕。
2. **啟動批次自動伺服守護（Batch-Level Ollama Auto-Serve）**：
   - 在 `start_app.bat` 與 `start_app_dev.bat` 掛載時，自動探測 `127.0.0.1:11434`，若未啟動則自動尋找本機 `ollama.exe` 並於背景執行 `ollama serve`。符合 Windows batch 規範（CRLF、`chcp 65001`）。
3. **前端即時錯誤通知與 HTTP 400 契約收斂**：
   - 在 `src/web/routers/pod_router.py` 將推論引擎之 `RuntimeError` 捕捉並包裝為 FastAPI `HTTPException(status_code=400, detail=str(e))`，使前端 `pod_studio.html` 之 `toolbox.errorPanel()` 與 Toast 能立即彈出清晰紅框提示，不再靜默無感。
4. **模型下載與管理解耦**：
   - 模型下載回歸標準 CLI / 工具手動管理流程，保持後端核心代碼與推論管線純粹，避免在 Python 代碼內嵌入隱式背景線程下載。

### Consequences

- 徹底消除因模型未安裝或服務離線而產生的 Gemini 404 報錯與非預期雲端扣款。
- 前端使用者能獲得直接、明確的模型狀態指導，本機環境在無介入下即可自動喚醒 Ollama 服務並啟動下載。

### Related Bug

BUG-011

---

## ADR-012 — PDF 行重組純運算層隔離、三層分工架構與版面語意解耦

### Status

Accepted

### Context

在自動整稿與出版排版管線中，既有 PDF 抽取邏輯面臨雙重痛點：

1. **短標題併入內文**：少字數標題缺乏版面與語意區隔，被錯誤併入內文，導致 Word 樣式套用失敗且難以使用尋找替換批次修正。
2. **正文段落破碎截斷**：內文行受限於 PDF 物理排版被當成獨立行，字型微調（如局部粗體、拉丁學名）直接觸發斷段，全形標點換行誤插入空格。
3. **過度耦合**：既有模組將「物理換行判斷」、「段落邊界判斷」與「標題層級判斷」混為一談，任何啟發式規則調整皆引發連鎖誤判。

### Decision

1. **三層分離架構（Three-Tier Decoupling）**：
   - **Tier 1 (Paragraph Reconstruction)**：純運算模組，負責將 PDF 物理行重組為語意段落（`ParagraphRecord`），保留 Span 脈絡、計算字符加權字體特徵、追蹤成對符號堆疊、輸出可追溯邊界證據（`BoundaryEvidence`）與跨頁延續旗標。**嚴禁在此層輸出標題分類語意**（`semantic_role="uncertain"`, `heading_level=None`）。
   - **Tier 2 (P1 Layout + P2 Semantic Classifier)**：基於 `ParagraphRecord` 的綜合版面幾何（字體差異、行距、縮排、置中）與上下文語意（章節正則、TOC 校驗、LLM 語意複核）進行角色分類。
   - **Tier 3 (DOCX Style Mapping)**：依據 Semantic Role 映射至 Word 樣式範本。
2. **單欄閱讀順序確定性契約（Single-Column Contract）**：
   - Phase 1 明確限定單欄排版輸入，依 `(line.bbox[1], line.bbox[0])` 進行確定性排序，不臆測多欄閱讀流。
3. **跨頁符號優先級（Delimiter Precedence）**：
   - 頁尾判斷中，未閉合成對符號（如未收合之引號、書名號、括號）具最高優先級，覆蓋內部之句末標點符號。

### Consequences

- 段落重組模組具備純運算性質（無磁碟 I/O、無外部依賴），可完全獨立進行單元測試與離線驗證。
- 為後續 Phase 2 標題版面分類器提供了強型別、字符加權、幾何邊界明確的 `ParagraphRecord` 輸入基礎。

### Related Bug

BUG-012

---

## ADR-013 — 字型級 AI 版面預判快取、結果持久化回寫 `fonts.json` 與人工審核確認直通架構

### Status

Accepted

### Context

在處理長篇多文字與腳注書籍（如 450 頁之《忽必烈》）時，既有 `book_layout_extractor.py` 架構暴露出四項效能與排版缺陷：

1. **先執行逐頁 LLM 推論、事後才因已綁定字型而丟棄**：迴圈在檢查 `font_role_map`（`config/fonts.json` 已確認字型樣式）與目錄/章節 Regex 之前，無條件將每頁短句送入 Ollama `review_uncertain_layout`，等耗時數秒推論返回後，才因 `_has_font_mapping == True` 將 AI 結果拋棄，且未將未知字型之 AI 判定結果持久化回寫至 `config/fonts.json` 供人工審核。
2. **正常段落首行縮排誤觸發逐頁 LLM 邊界審查與斷句幻覺**：將 `abs(current_bbox[0] - previous_bbox[0]) >= 10.0` 列為不確定邊界，導致中文書籍每個標準段落首行縮排（約 20pt）回退至第二行左邊界時均觸發 Ollama `review_uncertain_boundaries`，不僅使 450 頁書籍耗時長達數十分鐘，更因模型幻覺將跨行詞語（如「準備進 / 攻南宋」、「才讓怯 / 薛長」）腰斬為獨立段落。
3. **混合 Span 區塊字型角色被前導數字遮蔽**：章節標題（如 `1　風雲突變`）前導阿拉伯數字使用西文字型（`E-BZ`），標題正文使用中文字型（`FZS3K`），原查找邏輯直接取第一個 Span 導致誤套用西文字型的 `Normal` 樣式。
4. **頁底腳注區塊未依 2D 行序重排**：PDF 內部流順序將所有圓圈注標（`①`~`⑤`，位於 `x=132`）排在所有注釋內容（位於 `x=147`）之前，未經 2D 同行聚類排序直接遍歷導致 `①`~`④` 內容為空、全部注釋文字被合併塞入最後一筆 `⑤`。

### Decision

1. **人工確認字型直通車與 CJK 主導 Span 優先查找（Human-Confirmed Font Fast-Path）**：
   - 實作 `_extract_primary_font_key()` 與 `_lookup_block_font_mapping()`，優先依 CJK 漢字字數權重選取區塊主導字型，防止前導編號西文字型遮蔽標題樣式。
   - 在進入 `review_uncertain_layout` 前先行檢查 `font_role_map`（`mapped_by == "user"`）、目錄索引與標準章節 Regex；已確認字型直接套用其綁定之 `.docx` 樣式，完全跳過 Ollama 推論。
2. **字型級 AI 預判快取與持久化回寫閉環（Font-Level AI Deduplication & Persistence for Human Review）**：
   - 對尚未經人工確認之未知字型短句，以 `font_name (size_pt)` 為單位進行全書去重快取（`ai_font_decision_cache`），同一字型群組全書僅呼叫 `review_uncertain_layout` 一次。
   - 推論結果彙整於 `audit_data["ai_layout"]["retained_font_suggestions"]`，並於 `process_book_vector_pdf` 完成時透過 `save_ai_layout_suggestions_to_fonts_json()` 以 `"mapped_by": "ai_layout"` 非破壞性寫回 `config/fonts.json`（絕不覆蓋 `"mapped_by": "user"` 紀錄，且維持 `_parse_pdf_layout_flow` / `extract_book_vector_ast` 的 Zero-Disk-IO 純函數契約）。
   - 前端「字體審查」（`analyze_pdf_for_ui`）自動載入 `ai_layout` 預判角色與 `.docx` 樣式供人工審核，確認儲存後轉為 `"mapped_by": "user"` 永久保留。
3. **移除向量通道逐頁縮排 LLM 邊界覆寫並強化物理樣式切段**：
   - 在 `book_layout_extractor.py` 移除逐頁 `review_uncertain_boundaries` 呼叫，段落分合完全交由確定性樣式邊界（`docx_style`、字體角色、主導 CJK 字型/字級變換）、未閉合標點堆疊與幾何縮排/行尾滿行度決定。
4. **頁底腳注 2D 水平行聚類排序（`_sort_blocks_by_row_and_x`）**：
   - 在解析頁底腳注前，對 `footnote_blocks` 依垂直中心點容差（`y_tol=5.0pt`）聚類為水平行並按 `x0` 由左至右排序，確保注標與同行注釋文字精準配對。

### Alternatives

- **替代方案 A**：保留每頁對同一字型重複呼叫 `review_uncertain_layout`。450 頁將產生 450+ 次冗餘推論，耗時數十分鐘且毫無額外資訊增益。
- **替代方案 B**：直接在 `_parse_pdf_layout_flow` 內部寫入 `config/fonts.json`。這會違反 `extract_book_vector_ast` 的 Zero-Disk-IO 契約（`test_vector_ast.py`），故將檔案持久化收斂於外層 `process_book_vector_pdf`。

### Consequences

- 已完成字體審核之書籍（如《忽必烈》）Ollama 呼叫次數降為 0，450 頁整稿時間由 15~50 分鐘縮短至數秒。
- 新書籍首次整稿時，未知字型經 `review_uncertain_layout` 處理完的結果完整保留於 `config/fonts.json` 供人工審核確認後永久綁定 `.docx` 樣式。
- 徹底根除跨行句子被腰斬與頁底多筆腳注錯位合併之排版缺陷。

### Related Bug

BUG-013
