# 🚀 專案發布與未來更新 SOP

本專案採用**雙軌更新機制**（主程式與 AI 模型分離），以確保終端用戶能以最少的時間完成更新（通常小於 50MB）。

---

## 👩‍💻 開發者發布流程 (Developer Workflow)

當您完成程式碼修改或新增功能，準備發布新版本給使用者時，請依循以下三個步驟：

### 1. 更新版本號
請開啟專案根目錄的 `version.json`，根據 [Semantic Versioning](https://semver.org/) 更新版本號：
```json
{
  "app_version": "1.2.0",
  "model_version": "1.0.0",
  "model_hash": "sha256:default",
  "min_compatible_model": "1.0.0"
}
```
* 若僅是程式碼功能新增/修復，請只修改 `app_version`。
* 若有更換新的 YOLO/AI 權重模型，請同時修改 `model_version` 與 `min_compatible_model`。

### 2. 提交並標籤 (Commit & Tag)
使用 Git 提交您的修改，並建立帶有 `v` 開頭的版本標籤（請與 version.json 中的版本號一致）：
```bash
git add .
git commit -m "feat: release version 1.2.0"
git tag v1.2.0
```

### 3. 推送至遠端 (Push to GitHub)
將標籤推送至 GitHub 專案庫：
```bash
git push origin master
git push origin v1.2.0
```

🎉 **就這麼簡單！** 
推送到 GitHub 後，GitHub Actions 的 Release Workflow 會自動觸發。它將在雲端使用 PyInstaller 乾淨地編譯出不含 300MB 權重的純淨版 EXE，並自動附在 GitHub Release 中！

---

## 📦 模型升級處理
若您更新了 AI 模型權重檔，由於權重檔大於 GitHub 限制且不常變動：
1. 請自行將新的模型（例如 `yolo_v8_ft.onnx`）上傳至該版本的 GitHub Release Assets 或 Google Drive。
2. 使用者端的主程式在啟動時，若偵測到 `model_version` 過舊，會提示使用者手動下載最新模型檔並放置於 `models/` 或 `config/` 資料夾中。

---

## 💻 使用者更新體驗 (User Experience)

1. 使用者在軟體左下角點擊「**🔄 檢查更新**」。
2. 系統向 GitHub 查詢是否有比本地更新的版本。
3. 跳出確認視窗，顯示新版發布說明（Release Notes）。
4. 使用者點擊「立即下載並重啟」。
5. 系統在背景將 30~50MB 的純執行檔下載至 `PDF_Toolkit.exe.new`。
6. 下載完成後，系統呼叫 `updater.bat` 並自動退出。
7. `updater.bat` 在背景安靜覆蓋舊檔案，並重新啟動軟體，實現**無縫熱更新**！
