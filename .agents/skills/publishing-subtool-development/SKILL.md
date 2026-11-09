---
name: publishing-subtool-development
description: 開發出版社新專項子工具模組（Auxiliary Task）的標準全流程指南與架構規範。當需要新增出版子工具（如版權頁與 ISBN 校驗、目錄章節比對、生僻字校對、表格專項檢查等）時，請遵循此 Skill 進行模組註冊、API 契約定義、前端標準工作台建置與驗收測試。
---

# 出版專項子工具模組開發標準工作流 (Publishing Sub-tool Development Workflow)

本專案採用**「單核心 + 可插拔專項工作任務底座」（Single-Core + Pluggable Task Foundation）**架構。
在開發任何新的出版社專項子工具功能時，**嚴禁**將子工具特定邏輯硬編碼塞入核心整稿管線（`book_layout_extractor.py`、`md_to_docx.py` 或 `ocr_router.py`）。所有新子工具必須作為獨立可插拔單元實作並註冊至 `TaskPluginRegistry`。

---

## 1. 系統架構定位與分類規範

系統將所有功能嚴格劃分為兩大類別（`TaskCategory`）：

| 類別識別碼 (`category`) | 定位與用途 | 側邊欄與首頁對應位置 | 現有模組範例 |
| :--- | :--- | :--- | :--- |
| `core_typesetting` | **核心引擎：書稿排版與整稿管線** | 側邊欄 `Settings > 一般與工作流設定` & 首頁主流程卡片 | `ocr_pipeline`（全自動整稿）、`pod_studio`（POD 整稿） |
| `auxiliary_task` | **可插拔專項子工具** | 側邊欄 `Settings > OCR 與識別設定 > 輔助工具` & 首頁輔助工具清單 | `founder_repair`（方正修復）、`extract_images`（圖片提取）、`formula_extraction`（公式提取） |

### 核心架構鐵律（Architectural Invariants）

1. **零侵入原則**：新增子工具時，不應修改 `sidebar.js` 的靜態陣列或 `index.html` 的硬編碼清單；前端會自動透過 `GET /api/system/plugins` 動態發現並渲染所有 `is_enabled=True` 的外掛。
2. **GPU 資源互斥保護**：若新子工具涉及本地 VLM（Ollama）、YOLO 視覺偵測或高 VRAM 消耗運算，**必須**在執行區段使用 `async with get_gpu_semaphore():`（由 `src.web.dependencies` 匯入），防止 RTX 3060 12GB 環境發生 VRAM OOM 崩潰。
3. **非同步生命週期與可取消性**：背景長耗時任務必須透過 `TaskQueue`（`src.utils.task_queue`）管理，並支援使用者中途取消與暫存檔自動清理。
4. **檔案交付雙模閉環**：所有產出檔案除了支援本機原生另存新檔對話框（`/api/tools/save_file_dialog`）外，**必須**提供 HTTP 下載端點（`fallbackUrl`），確保區域網路（LAN）或遠端瀏覽器連線時能無縫降級下載。
5. **嚴格型別契約與零靜默降級**：所有 API 端點必須在 `src/web/schemas.py` 定義 Pydantic v2 `BaseModel`（含 `extra="forbid"`），並執行 `generate_ts_contracts.py` 同步更新 `frontend/src/types/contracts.ts`。

---

## 2. 開發新子工具的 6 步標準工作流

假設我們要開發一個新的專項子工具：**「版權頁與 ISBN 校驗器」（`isbn_checker`）**，請依序執行以下 6 個步驟：

### Step 1：建立核心領域運算模組

在 `src/` 下建立獨立的領域套件（或在對應子目錄新增模組），確保核心演算法與 Web 框架（FastAPI）完全解耦，方便單獨進行單元測試：

- 路徑範例：`src/isbn_checker/__init__.py`、`src/isbn_checker/core.py`
- 規範：
  - 輸入與輸出應使用明確的 Python `dataclass` 或 `Path` 物件。
  - 禁止在核心演算法中直接讀取 FastAPI `UploadFile` 或全域 Web 狀態。
  - 若需呼叫本地 Ollama 或雲端 Gemini，統一透過 `src/utils/ollama_client.py` 進行呼叫，並遵守「零靜默降級政策」（當指定模型不可用時明確拋出錯誤，禁止私自降級）。

### Step 2：定義 Pydantic 嚴格契約並同步 TypeScript 型別

1. 打開 `src/web/schemas.py`，新增該子工具的 Request / Response 契約模型：

   ```python
   class IsbnCheckResponse(StrictContractModel):
       """POST /api/isbn/check 回應契約"""
       status: Literal["success", "error"]
       task_id: str
       isbn_detected: str = ""
       is_valid: bool = False
       download_url: Optional[str] = None
       message: str = ""
   ```

2. 打開 `src/scripts/generate_ts_contracts.py`，將 `IsbnCheckResponse` 加入 `EXPORTED_MODELS` 清單。
3. 執行契約同步腳本並驗證：

   ```bash
   python src/scripts/generate_ts_contracts.py
   python src/scripts/generate_ts_contracts.py --check
   ```

### Step 3：實作 `BaseTaskPlugin` 與 FastAPI Router

在 `src/web/routers/` 建立路由模組（例如 `src/web/routers/isbn_router.py`），或在 `src/plugins/` 下定義外掛類別：

```python
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.plugins.base import BaseTaskPlugin, TaskPluginSpec
from src.web.dependencies import CFG, PATHS, get_gpu_semaphore, save_upload_file_safely
from src.web.schemas import IsbnCheckResponse

router = APIRouter(tags=["isbn_checker"])

@router.post("/api/isbn/check", response_model=IsbnCheckResponse)
async def check_isbn_endpoint(file: UploadFile = File(...)) -> IsbnCheckResponse:
    # 1. 安全儲存上傳檔案（強制檢查檔案大小上限）
    safe_name = Path(file.filename or "input.pdf").name
    temp_input = PATHS.temp_base / f"isbn_{safe_name}"
    await save_upload_file_safely(file, temp_input, max_mb=CFG.max_upload_size_mb)

    # 2. 若需 GPU 推論，必須加上 get_gpu_semaphore()
    # async with get_gpu_semaphore():
    #     result = await asyncio.to_thread(run_isbn_check, temp_input)

    return IsbnCheckResponse(
        status="success",
        task_id="isbn_001",
        isbn_detected="978-957-00-0000-0",
        is_valid=True,
        download_url=f"/api/isbn/download/{safe_name}",
        message="版權頁 ISBN 校驗完成",
    )

class IsbnCheckerPlugin(BaseTaskPlugin):
    """版權頁與 ISBN 校驗專項任務外掛"""

    @property
    def spec(self) -> TaskPluginSpec:
        return TaskPluginSpec(
            id="isbn_checker",
            name="ISBN 版權校驗",
            category="auxiliary_task",
            description="自動解析書籍版權頁 CIP 與 ISBN 條碼，檢驗核對字軌與出版資訊一致性。",
            entry_url="/static/isbn_checker.html",
            api_prefix="/api/isbn",
            icon="check",  # 對應 sidebar.js ICON 字典鍵值 (book, doc, pod, formula, image, wrench, check, shield, cpu)
            allowed_input_exts=[".pdf", ".docx"],
            output_types=["json", "docx"],
            requires_gpu=False,
            is_enabled=True,
            order=130,
        )

    def get_router(self) -> Optional[APIRouter]:
        return router
```

### Step 4：註冊至 `TaskPluginRegistry` 與掛載路由

1. 打開 `src/plugins/registry.py`，在 `_initialize_builtins()` 中註冊新外掛（或由 `app.py` 啟動時透過 `registry.get_routers()` 自動掛載）：

   ```python
   self.register(IsbnCheckerPlugin())
   ```

2. 若該外掛附帶獨立的 `APIRouter`，確保在 `src/web/app.py` 中透過 `app.include_router(...)` 掛載，或在 `app.py` 迴圈掛載 `get_plugin_registry().get_routers()`。

### Step 5：建立前端標準工作台頁面（使用 `StandardTaskClient`）

在 `src/web/static/` 下建立對應的 HTML 工作台頁面（例如 `src/web/static/isbn_checker.html`）：

1. **引入共用基礎設施**：

   ```html
   <link rel="stylesheet" href="/static/sidebar.css">
   <link rel="stylesheet" href="/static/toolbox.css">
   <script src="/static/js/viewport_manager.js"></script>
   <script src="/static/sidebar.js"></script>
   <script src="/static/js/task_client.js"></script>
   <script src="/static/js/native_bridge.js"></script>
   ```

2. **使用 `StandardTaskClient` 處理任務提交、SSE/輪詢進度與取消**：

   ```javascript
   const taskClient = new window.StandardTaskClient();

   async function runSubtoolTask(formData) {
       try {
           const initData = await taskClient.submitTask('/api/isbn/check', formData);
           // 若為非同步長任務 (回傳 task_id)，啟動雙模監聽：
           if (initData.task_id) {
               taskClient.listen(initData.task_id, {
                   onProgress: ({ progress, message }) => {
                       updateProgressBar(progress, message);
                   },
                   onComplete: (finalData) => {
                       renderSuccessResult(finalData);
                   },
                   onError: (err) => {
                       window.toolbox.notify(err.message, 'error');
                   },
                   onCancel: () => {
                       window.toolbox.notify('任務已取消', 'warning');
                   }
               });
           }
       } catch (err) {
           window.toolbox.notify(err.message, 'error');
       }
   }
   ```

3. **使用 `NativeBridge.saveOutputFile` 支援本機對話框與遠端下載雙模交付**：

   ```javascript
   await window.NativeBridge.saveOutputFile({
       sourcePath: result.output_path,
       fallbackUrl: result.download_url, // 必填！確保遠端瀏覽器可下載
       suggestedFilename: result.suggested_filename,
       buttonEl: downloadBtn
   });
   ```

### Step 6：撰寫自動化測試與驗收

在 `tests/` 目錄下新增或擴充測試（參考 `tests/test_plugin_task_architecture.py`）：

1. **外掛規格與驗證測試**：確認 `registry.get("<plugin_id>")` 存在，且 `plugin.validate_input()` 正確攔截非法副檔名。
2. **動態發現 API 測試**：呼叫 `GET /api/system/plugins?category=auxiliary_task`，確認新子工具出現在回傳清單中。
3. **端到端功能與契約測試**：使用 `TestClient(app)` 測試上傳、處理與下載端點，確保回傳格式 100% 符合 `src/web/schemas.py` 定義。

---

## 3. 交付前檢查清單 (Pre-Delivery Checklist)

在完成新子工具開發並準備提交前，請逐一核對以下項目：

- [ ] **外掛註冊檢查**：`GET /api/system/plugins` 是否能正確回傳新子工具的 `id`、`name`、`entry_url` 與 `output_types`？
- [ ] **副檔名白名單檢查**：`allowed_input_exts` 是否已正確設定，且前端 `<input type="file" accept="...">` 與後端驗證一致？
- [ ] **上傳大小防護**：後端是否使用 `save_upload_file_safely(file, dest, max_mb=CFG.max_upload_size_mb)`，前端是否呼叫 `window.checkUploadFileSize(file)`？
- [ ] **GPU 號誌鎖防護**：若使用到 GPU / Ollama / YOLO，是否已包裹 `async with get_gpu_semaphore():`？
- [ ] **雙模下載閉環**：`NativeBridge.saveOutputFile` 是否同時傳入 `sourcePath` 與非空的 `fallbackUrl`？
- [ ] **跨工作台串接（選填）**：若子工具產出為乾淨的 `.docx`（如方正修復），結果卡片是否提供「接續送入 POD 整稿 →」按鈕（跳轉至 `/static/pod_studio.html`）？
- [ ] **TypeScript 契約同步**：執行 `python src/scripts/generate_ts_contracts.py --check` 是否回傳 `Verified`？
- [ ] **全量回歸測試**：執行 `pytest tests/` 是否全數通過且零退化？
