# 🛡️ 系統脆弱性與防護審查報告 (Attack / Issue Review Report)

這份報告旨在分析目前本地端專案（公式書籍轉檔）在各個演進階段可能遭遇的「系統崩潰風險」與「極端條件攻擊（邊界條件）」，並作為驗證修復是否完善的標準。

---

## 🥇 第一階段：底層穩定性與資源釋放 (Stability)

### 🚨 潛在風險：Resource Exhaustion & Type Confusion
* **攻擊/觸發條件**：
  1. **副檔名偽裝攻擊 / 格式錯誤**：使用者（或腳本）將一個 `.jpg` 或 `.exe` 檔案改名為 `book.pdf` 並傳入 `hybrid_engine.py` 或 `core_agent.py`。
  2. **資源洩漏 (Handle Leak)**：傳入一個內部結構損毀的 PDF，當 PyMuPDF 遍歷頁面 (`for page in doc`) 發生例外拋出時，迴圈中斷，未執行到底部的 `doc.close()`。當批次處理幾千個檔案時，作業系統會報錯 `Too many open files` 導致崩潰。
* **攻擊模擬腳本**：
  ```python
  # 模擬 1000 次崩潰
  import os
  with open("fake.pdf", "wb") as f:
      f.write(b"not a pdf")
  
  for _ in range(1000):
      # 若無 try...finally 保護，這將在幾百次後耗盡 File Handles
      agent.extract_formulas()
  ```
* **驗證目標**：確保輸入端有嚴格的 `pdf_path.lower().endswith('.pdf')` 檢查，並確定所有 `fitz.open()` 都有 `try...finally: doc.close()` 保護。

---

## 🥈 第二階段：資源限制防護 (Guardrails)

### 🚨 潛在風險：Out of Memory (OOM) "Zip Bomb" 等級崩潰
* **攻擊/觸發條件**：
  * **超高解析度 OOM**：傳入一個尺寸異常巨大的 PDF（例如單頁長寬超過 100,000 pt），當以 300 DPI 渲染為 numpy array 時，會瞬間佔用數十 GB 的 RAM，導致作業系統直接死機 (Freeze) 或被 OOM Killer 砍掉。
  * **無窮頁數 OOM**：上傳一份 5,000 頁的數學論文合集。由於模型處理完的暫存張量 (Tensors) 未積極呼叫 Garbage Collection 或未限制單次 Batch，最終把顯示卡 (VRAM) 塞爆。
* **攻擊模擬腳本**：
  ```python
  import fitz
  # 製造惡意 PDF
  doc = fitz.open()
  page = doc.new_page(width=100000, height=100000) # 超大長寬
  doc.save("malicious_bomb.pdf")
  ```
* **驗證目標**：在設定檔中建立 `MAX_PDF_PAGES`、`MAX_PDF_WIDTH`，並於載入頁面時檢查。超過尺寸則拒絕處理，或是採用分批處理（每 50 頁手動清理記憶體）。

---

## 🥉 第三階段：環境固化 (DevOps)

### 🚨 潛在風險：Dependency Hell (DLL Load Failed)
* **攻擊/觸發條件**：
  * 當專案移交給另一台電腦時，由於沒有精確綁定套件版本（只有 `import cv2`），新環境 pip 預設安裝了 `numpy 2.x`。然而，開源庫 Pix2Text 或 OpenCV 可能尚未相容 Numpy 2.x，導致在 `import cv2` 時直接引發 `ImportError: DLL load failed` 或 `C API ABI mismatch`。
* **驗證目標**：產生精確的 `requirements.txt`（包含 `numpy<2.0.0`, `opencv-python-headless==4.9.0.x` 等）。甚至使用 Docker 完全隔離 Host OS。

---

## 🏅 第四階段：介面擴展 (Web UI)

### 🚨 潛在風險：Path Traversal & Race Conditions (競爭危害)
* **攻擊/觸發條件**：
  * 當升級為 Streamlit 多人同時使用時，若兩人同時上傳不同 PDF，但後端程式碼依賴 `config.PATHS.temp_pdf`（寫死的全域單一路徑 `data/02_intermediate/temp_cropped_optimized.pdf`）。
  * 結果：User B 的 PDF 覆蓋了 User A 的暫存檔，User A 收到的 Word 是 User B 的內容。
  * **Path Traversal**：上傳檔名若未經 Sanitization（例如命名為 `../../../etc/passwd.pdf`），可能在 `os.path.join` 存檔時覆蓋掉系統關鍵檔案。
* **攻擊模擬腳本**：
  ```python
  malicious_filename = "../../../windows/system32/important.dll"
  os.path.join(output_dir, malicious_filename) # 成功逃逸目錄
  ```
* **驗證目標**：改用 `tempfile.NamedTemporaryFile` 或動態 UUID 資料夾處理併發的檔案上傳；並嚴格過濾上傳檔名。


## 📌 GitHub 版本控制與專案維護規範

本專案嚴格遵循以下開發與維護原則：

1. **即時更新原則**：遇到「功能性」上程式邏輯的修改，請在完成修改後一併同步修改根目錄的 README.md。若是任務具有階段性，則全部完成後主動提醒使用者是否該修改 README.md。
2. **網頁功能更新日誌**：若是更新或新增網頁功能，則必須在 README.md 中補充更新日誌說明。
