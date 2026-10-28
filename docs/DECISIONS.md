# Architectural Decision Records (DECISIONS.md)

本文件依據 `decision-log` 規範維護專案關鍵架構與設計決策紀錄（ADR）。

## 歷史決策索引（Historical ADRs referenced in `docs/BUG_LOG.md`）

- **ADR-003 — 字體審閱預設自動規則與雙通道章節標題擴充**：前端字體 Modal 預設改為 `auto`，擴充章節正則與 TOC 前導點過濾，並支援 Surya `surya_text`。
- **ADR-004 — 管線原子性與 Surya 0.6 模型對齊守則**：子程序失敗或目標檔案未實體生成時嚴禁回報 `progress: 100`，強制使用 Surya 0.6 官方模型架構。
- **ADR-005 — 特殊符號映射與 2D 卡片閱讀流守則**：建立 `symbol_mapping.json` 還原帶圈數字與括號，實作 2D 橫帶聚類排序，並在 Pandoc 停用 `subscript`（`-subscript`）。
- **ADR-006 — OCR 雙軌混合解析與圖文環繞段落合併架構**：優先映射原生向量文字層，對高度 `>35px` 區塊執行水平投影單行切片（`_slice_box_into_lines`），並支援圖文環繞斷行合併。

---

# ADR-007 — 雙通道 2D 座標三線表重建、視覺裁切取代頁眉啟發式刪除、管線預設無腳注與強型別算子契約

## Status
Accepted

## Context
在處理醫學與學術出版書籍（如《強直性脊柱炎》）時，既有架構暴露出五項系統性缺陷：
1. **三線表失明與首字框誤判**：PyMuPDF `page.find_tables()` 僅能偵測四邊封閉格線表，對無垂直線之標準學術三線表檢出率為 0%，卻將 35 個章節首字下沉裝飾框誤判為 `1x2` 表格；失去表格邊界後，跨列垂直置中的儲存格（如 `刺络埋线组 43`）因 `y0` 居中而穿插至錯誤資料列。
2. **雙重頁眉過濾誤殺表頭**：使用者已於前端透過紅藍綠四向裁切滑桿（`set_cropbox`）人工裁除頁眉頁尾，但後端 `book_layout_extractor.py` 仍執行硬編碼 `is_page_header()`（頂部 11% 且含 `/` 即刪除），導致位於頁面頂端的表格表頭（含 `ESR（mm / h）`）被整行抹除。
3. **特殊標記腳注誤傷內文編號**：出版社來稿無特殊標記注腳參照，預設開啟腳注偵測會導致頁底條列或表注被誤抽離。
4. **POD 通道缺乏原始 PDF 幾何上下文**：POD 階段一僅上傳預修 `.docx`，階段二無法得知後半部被壓平的純文字段落（如表 4）在原 PDF 中實為三線表。
5. **Python 裸 `dict` 引發跨模組欄位幻覺**：表格與版面區塊以無結構 `dict` 傳遞，容易在跨通道優化時產生鍵名不一致。

## Decision
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

## Alternatives
- **替代方案 A**：調高 PyMuPDF `find_tables(strategy="text")` 敏感度。實測該策略對《強直性脊柱炎》P.156~160 仍回傳 0 個表格，且會在普通正文產生大量假表格。
- **替代方案 B**：直接修改底層函式簽章 `enable_footnotes: bool = False`。這會破壞既有 `tests/test_p1_refactoring.py` 的簽章反射測試；在業務調用層（UI/API/Dispatcher/POD）預設關閉更為穩健。

## Consequences
- 向量通道與純 OCR 通道共用同一套 2D 表格重建算子，三線表及頂部含 `/` 單位之表頭可 100% 完整保留並轉為 Word `Table Grid`。
- POD 通道可在不重新執行全書初稿轉檔的情況下，直接透過階段一綁定之原 PDF 將未精修區段的殘缺文字表升級為真實 Word 表格。
- 嚴格遵守 `test_vector_ast.py` 的 Zero-Disk-IO、檔案控制代碼釋放與 Golden SHA-256 基準。

## Related Bug
BUG-007

---

# ADR-008 — P2 雙向強型別契約鐵籠與 Schema-Driven TypeScript 自動生成架構

## Status
Accepted

## Context
前端 HTML/JS 與後端 Python 之間若缺乏編譯期與執行期雙向型別契約，且內部以鬆散 `dict[str, Any]` 傳遞版面結構（如 `layout_records`），Agent 在跨端優化演算法時極易產生欄位名稱幻覺（Key Hallucination）或靜默漏欄。此外，Windows 離線執行環境未必安裝 Node.js，型別生成工具不可強依賴外部 `npm` 才能產出契約。

## Decision
1. **鐵律一（Zero Raw-Dict Policy）**：
   - 新增 [`src/extraction/contracts.py`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/extraction/contracts.py) 與 [`src/web/schemas.py`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/web/schemas.py)，統一開啟 `ConfigDict(extra="forbid")`，任何未定義欄位立即觸發 `ValidationError`。
2. **鐵律二（Schema-Driven Pure-Python OpenAPI -> TypeScript Codegen）**：
   - 新增 [`src/scripts/generate_ts_contracts.py`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/scripts/generate_ts_contracts.py)，直接反射 Pydantic v2 JSON Schema 自動生成 [`frontend/src/types/contracts.ts`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/frontend/src/types/contracts.ts)（含可辨識聯合型別 `PropagationPayload`、`LayoutRecordContract`、`PodSessionPhase`），並支援 `--check` 防漂移校驗。
3. **鐵律三（TypeScript 前端狀態機與雙重靜態校驗閘門）**：
   - 建立 [`frontend/src/api/podClient.ts`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/frontend/src/api/podClient.ts) 與瀏覽器原生 ES 模組 [`src/web/static/js/pod_contracts.js`](file:///c:/Users/sonbo/Desktop/%E6%9B%B8%E7%B1%8D%E8%BD%89%E6%AA%94%E5%85%AC%E5%BC%8F%E6%8F%90%E5%8F%96%EF%BC%8Fword%E8%A3%81%E5%88%87%E9%82%8A%E7%95%8C%E5%8C%85/git_doc-image-extractor/doc-image-extractor/src/web/static/js/pod_contracts.js)，透過 `pyright` + `pytest tests/test_p2_strict_contracts.py` 執行零誤差契約檢驗。

## Consequences
- 演算法算子輸出之 `layout_records`（如 `TableLayoutContract` 新增 `caption_text`）若未同步宣告於契約中，單元測試將立即攔截。
- 即使在無 Node.js 的純 Python 部署環境，仍可 100% 自動生成與校驗 TypeScript 契約定義。


