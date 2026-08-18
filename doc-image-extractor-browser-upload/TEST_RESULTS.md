# 測試結果

## 核心管線

以合成測試檔案驗證 PDF 與 DOCX：各成功提取 1 張圖片，PDF 產生 PNG，DOCX 保留原始 PNG 位元內容，ZIP 建立成功。測試輸出：`Pipeline test passed`。

## Streamlit 網頁

使用 `streamlit run app.py --server.headless true --server.address 127.0.0.1 --server.port 8501` 啟動後，健康端點回傳 `ok`，服務日誌顯示綁定於 `127.0.0.1:8501`。

瀏覽器驗證成功上傳 `sample.pdf` 與 `sample.docx`，頁面顯示「已選取 2 個檔案」。點選「開始提取圖片」後顯示處理完成、處理文件 2、提取圖片 2、警告訊息 1；PDF 與 DOCX 各顯示 1 張圖片，並出現「下載全部圖片 ZIP」按鈕。DOCX 的 1 個非圖片媒體檔案被正確列為略過警告。

## IP 綁定

本次測試使用 `127.0.0.1`，未使用 `0.0.0.0`、公開隧道、反向代理或第三方 API。此模式只提供本機瀏覽器使用。
