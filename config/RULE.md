# 🛡️ 專案開發與版本控制規範 (RULE.md)

本專案定義系統架構安全、極端條件防護、以及 GitHub 版本控制維護之最高指導準則。

---

## 📌 GitHub 版本控制與專案維護規範

1. **即時更新原則 (README 同步)**：
   * 凡遇到「功能性」上程式邏輯的修改（例如：新增 API、修改系統架構、變更裁切邏輯、修復崩潰等），請在完成修改後**一併同步修改根目錄的 `README.md`**，確保專案文件永遠與最新程式碼保持一致。
   * 若任務具有「階段性」（例如跨多個子任務的大型重構），則在**該階段全部完成後**，主動提醒使用者是否需要為此次更新調整 `README.md`。

2. **網頁功能更新日誌 (Changelog)**：
   * 若是更新或新增網頁版（Web UI）功能（例如：新增錯誤回報機制、動態裁切預覽滑桿、拖曳上傳等），必須在 `README.md` 中的「更新日誌 (Changelog)」章節中補充版本紀錄說明。

3. **Git Commit 規範**：
   * 遵循 Conventional Commits 格式（例如 `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`）。
   * 嚴禁將超過 GitHub 上限（100MB）的大型二進位檔案（如整本測試 PDF、生成大型 docx）提交至 Git 歷史紀錄中。

---

## 🛡️ 系統脆弱性與極端防護標準 (Security & Stability Guardrails)

### 第一階段：底層穩定性與資源釋放 (Stability)
* **副檔名偽裝防護**：輸入端必須嚴格驗證 `.pdf` 副檔名與檔案簽章，防止 Type Confusion。
* **資源洩漏防護 (Handle Leak)**：所有 PyMuPDF `fitz.open()` 物件皆需封裝於 `with fitz.open(...) as doc:` 或 `try...finally: doc.close()` 中，避免批次處理時引發 `Too many open files`。

### 第二階段：資源限制防護 (Guardrails)
* **記憶體防爆 (OOM Guardrail)**：
  * 設定 `MAX_SAFE_PAGES` (預設 300 頁)，避免單次載入過長論文導致記憶體耗盡。
  * 每處理 `BATCH_SIZE` (預設 50 頁) 主動觸發 Python `gc.collect()` 與 `torch.cuda.empty_cache()`。
  * 設定 `MAX_IMAGE_WIDTH` (預設 4000 px)，對超大尺寸 PDF 頁面自動降階 DPI 渲染。

### 第三階段：相容性與環境隔離 (DevOps)
* **色彩空間相容 (CMYK Patch)**：`pdf2docx` 底層擷取 CMYK 圖片時易因 PyMuPDF 新版 PNG 寫入限制崩潰，系統需掛載 Monkey Patch 自動將四通道色彩轉換為 RGB。
* **精確環境鎖定**：維持 `requirements.txt` 版本邊界，確保跨作業系統部署之一致性。

### 第四階段：Web 介面安全與並行隔離 (Web Architecture)
* **路徑逃逸防護 (Path Traversal)**：使用者上傳之檔案需強制以 UUID / Sanitized Filename 重命名，禁止直接拼接未過濾的檔案路徑。
* **並行隔離 (Task Isolation)**：每個任務擁有獨立的 `task_id` 與暫存路徑，避免多使用者並行時覆蓋彼此的中繼檔案。
