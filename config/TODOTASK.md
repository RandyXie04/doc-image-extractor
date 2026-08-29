# 📋 待辦任務與靈感筆記清單 (TODOTASK.md)

本文件專門記錄未來的開發目標、功能待辦事項（Backlog）與架構靈感筆記，協助專案持續迭代與演進。

---

## 🚀 進行中 / 近期規劃 (Near-term Tasks)

### 📌 Task 1: 網頁內建回報彈窗 + 後端 GitHub API 自動開 Issue（免登入一鍵回報）
* **來源靈感**：錯誤回報機制方案二。
* **目標描述**：
  目前網頁端已實作「一鍵跳轉 GitHub 開 Issue」，但要求回報者必須具備 GitHub 帳號。未來可升級為內建彈窗模式：
  1. 使用者在網頁發生錯誤時，點擊「回報問題」跳出 Modal 彈窗。
  2. 彈窗內自動填入錯誤 Log，並提供備註欄位（讓使用者補充說明）。
  3. 使用者點擊「送出」，前端發送 POST 至後端 `/api/report-issue`。
  4. FastAPI 伺服器讀取 `.env` 中的 `GITHUB_BOT_TOKEN`，透過 GitHub REST API 自動以 Bot 身份在儲存庫建立 Issue。
* **技術細節與安全防護**：
  - 需實作 IP Rate Limit（每分鐘最多 3 次回報），防止惡意刷 Issue。
  - 後端 Log 脫敏處理（過濾掉機密路徑與敏感資訊）。

---

## 💡 中長期架構演進 (Medium & Long-term Backlog)

### 📌 Task 2: 分散式佇列與多使用者隔離 (Celery + Redis)
* **目標描述**：
  將現有的 `FastAPI.BackgroundTasks` 升級為標準分散式任務架構。
* **架構規劃**：
  * **Broker**: Redis
  * **Worker**: Celery Worker（可獨立橫向擴展，並支援專屬 GPU Worker）
  * **好處**：即便有多位使用者同時上傳數百頁的大型文檔，也不會互相搶佔主 API 伺服器資源，並支援任務排隊與重試機制。

### 📌 Task 3: 公式 OCR LaTeX 文字自動轉換 (Mathpix / Pix2Text LaTeX OCR)
* **目標描述**：
  目前系統僅裁切公式圖片（PNG）。未來可新增一鍵選項，將偵測到的公式圖片進一步呼叫 LaTeX OCR 模型，將圖片轉換為 `$$ ... $$` LaTeX 代碼，直接嵌入 Word 或生成 Markdown 筆記。

### 📌 Task 4: Docker 容器化與一鍵部署 (Containerization)
* **目標描述**：
  撰寫 `Dockerfile` 與 `docker-compose.yml`，將 Python 3.10+、PyMuPDF、CUDA/PyTorch、FastAPI 封裝為標準映像檔。
* **效益**：
  達到真正的「跨平台開箱即用」，徹底免除不同作業系統安裝 OpenCV 或 PyTorch 的環境配置問題。

### 📌 Task 5: 歷史任務管理與成果瀏覽面板
* **目標描述**：
  在前端加入「歷史轉檔紀錄」分頁，可直接在線上預覽過去處理過的 PDF 頁面、個別公式圖，並支援個別檔案重新下載。

---

## 📝 靈感隨手記 (Idea Scratchpad)
* *Idea*: 是否能支援多欄位（雙欄排版）論文的公式閱讀順序重構？
* *Idea*: 是否能加入 PDF 水印去背 (Alpha Transparency Extraction) 功能？
