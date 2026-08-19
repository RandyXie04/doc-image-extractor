# Streamlit Community Cloud 部署研究

來源：Streamlit 官方文件 <https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app>

關鍵結論：

1. 應用程式預設繼承 GitHub 儲存庫權限；私有儲存庫部署的應用程式預設是私有的。
2. Community Cloud 的 App settings → Sharing 可設定「This app is public and searchable」或「Only specific people can view this app」。
3. 私有應用程式可以在 Streamlit Community Cloud 中加入指定 viewer；預設只有 workspace developers 能看見。
4. 官方頁面說明公開／私有切換可從 App settings 進行，且只有 developers 能變更此設定。
5. 這表示「GitHub 私有 repo」本身不等於「公開分享」；若要用固定 URL 對外公開，需要在部署後把 App visibility 設為 public，或保留 private 並明確加入 viewer。

來源：Streamlit 官方 Secrets 文件 <https://docs.streamlit.io/develop/concepts/connections/secrets-management>

關鍵結論：

1. 官方不建議把未加密的 secrets 存放在 Git 儲存庫；應放在儲存庫外，例如環境變數或 secrets 檔案。
2. 專案層級的 `.streamlit/secrets.toml` 必須加入 `.gitignore`。
3. Streamlit Community Cloud 使用同一套 secrets 管理流程，但必須在 Community Cloud 的 Secrets Management console 設定 secrets。
4. 程式可透過 `st.secrets` 讀取部署端秘密設定；本專案將以此讀取驗證設定，而不把密碼或雜湊值寫進程式碼。

## 本機驗證測試

以測試環境變數 `APP_PASSWORD` 啟動 Streamlit 服務後，健康端點回傳 `ok`。未登入時頁面只顯示「文件圖片提取器」、存取密碼欄位與登入按鈕；上傳區、提取按鈕與下載功能均未顯示，表示驗證門檻在檔案處理流程之前生效。

正確密碼測試成功：輸入測試密碼後頁面顯示「登出」、檔案上傳區與處理說明；登入前不顯示上傳功能。此測試僅使用臨時測試密碼，未將任何正式密碼寫入檔案或儲存庫。
