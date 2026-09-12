---
name: python-pdf-workbench
description: 專門用於 Python PDF 轉檔、Pix2Text 深度學習公式萃取、FastAPI 非同步工作站與 Web 視覺化裁切預覽的架構與開發指引。
---

# Python PDF & Web 轉檔工作站開發技能 (Python PDF Workbench)

本技能提供開發與維護基於 Python (FastAPI / PyMuPDF / OpenCV / Pix2Text) 與 Web 原生前端的 PDF 轉檔與視覺化處理工作站之全方位開發標準與最佳實踐。

---

## 1. 核心管線與記憶體防護規範 (Guardrails)

處理數百頁高解析度學術 PDF 時，必須遵循以下資源管理原則：

1. **分批處理與主動垃圾回收 (Batching & GC)**：
   - 嚴格限制每批次處理頁數（預設 50 頁），並在每批次結束後主動呼叫 `gc.collect()` 釋放未引用記憶體。
   - 文件頁數超過安全上限（預設 300 頁）時應觸發防呆警告。
2. **動態 DPI 降級機制**：
   - 遇到尺寸過大的超大圖片（寬度 > 4000px）時，動態將 300 DPI 降級為 150 DPI 進行處理，避免記憶體溢出 (OOM)。
3. **色彩空間自動修復 (CMYK to RGB)**：
   - 對於印刷格式的 CMYK / DeviceCMYK 圖片，必須在進入 `pdf2docx` 之前自動轉碼為 RGB，避免底層 C 模組崩潰。

---

## 2. FastAPI 非同步與短輪詢架構

1. **長任務非同步化**：
   - 所有轉檔與公式辨識任務必須透過 `FastAPI.BackgroundTasks` 或獨立 Worker 執行，API Endpoint 僅負責接收檔案並立即回傳 `task_id`。
2. **狀態與進度管理**：
   - 使用線程安全字典或狀態儲存體記錄 `progress` (0-100%)、`status` (processing/completed/failed) 與 `logs`。
   - 前端採用短輪詢（每 1~2 秒請求 `/api/tasks/{task_id}/status`）或 SSE 推送即時進度。
3. **自動產物打包**：
   - 任務完成後，自動將產出的 DOCX 與公式圖檔 ZIP 包整理至獨立時間戳記目錄，提供單一打包下載連結。

---

## 3. Web 視覺化動態裁切預覽

1. **雙滑桿與輔助線渲染**：
   - 前端接收 PDF 第 1 頁（或指定頁）渲染圖，利用 Canvas 繪製紅藍輔助線（頂部裁切線與底部裁切線）。
   - 裁切數值傳遞至後端時需做精確的比例換算 (Display Scale to PDF Point/Pixel Scale)。
2. **無障礙與響應式**：
   - 支援拖曳上傳 (Drag & Drop)、檔案大小限制防呆、與即時錯誤吐司/彈窗提示。

---

## 4. 例外診斷與 GitHub Issue 一鍵回報

1. **日誌脫敏與診斷包**：
   - 擷取例外堆疊 (Stack Trace)、執行參數 (DPI、頁面範圍、裁切比例) 與系統環境資訊。
   - 脫敏過濾本機敏感檔案路徑或 API Token。
2. **回報機制**：
   - 支援 URL 參數預填 GitHub New Issue 頁面，或後端透過 GitHub REST API 自動建立 Issue。
