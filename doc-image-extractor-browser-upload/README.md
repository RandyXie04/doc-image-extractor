# 文件圖片提取器

這是一個以 Streamlit 製作的本機網頁工具，用來整合 PDF 與 Word（DOCX）內嵌圖片提取功能。使用者可以直接拖曳多個檔案上傳，按下提取後查看統計與縮圖預覽，再將所有圖片下載成單一 ZIP 檔。

## 功能

| 功能 | 行為 |
|---|---|
| PDF 圖片提取 | 讀取 PDF 內嵌圖片，輸出為無損 PNG；保留原程式對 DeviceN／CMYK 的色彩反相校正邏輯 |
| DOCX 圖片提取 | 讀取 `word/media/` 內的圖片，保留原始圖片副檔名與內容，不重新壓縮 |
| 多檔案處理 | 一次上傳多個 PDF／DOCX，結果會分來源文件顯示 |
| ZIP 下載 | 所有結果打包為一個 ZIP，並依來源文件建立子資料夾，避免同名檔案覆蓋 |
| 瀏覽器預覽 | 顯示前 12 張圖片；完整圖片仍會放入 ZIP。SVG、EMF、WMF 會打包但略過瀏覽器預覽 |
| 本機優先 | 程式不呼叫外部 API，也不會主動將文件上傳至第三方服務 |
| 公開服務驗證 | 以 `APP_PASSWORD_HASH` 進行共用密碼驗證；登入狀態 4 小時有效，單一工作階段連續失敗 5 次後暫停 5 分鐘 |
| 公開服務限制 | 單次最多 10 個檔案、總容量 500 MB；Community Cloud 另以 `maxUploadSize` 限制單檔容量 |

## 安裝

建議使用 Python 3.10 或更新版本，並在此專案目錄中建立虛擬環境：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS／Linux：

```bash
source .venv/bin/activate
```

安裝相依套件：

```bash
python -m pip install -r requirements.txt
```

## 公開部署前的密碼設定

公開分享時不要把實際密碼或 `.streamlit/secrets.toml` 放進 GitHub。本版本可完全透過瀏覽器設定密碼，不需要使用終端機：部署到 Streamlit Community Cloud 後，開啟 **App settings → Secrets**，貼入以下內容並替換成你自己的長密碼：

```toml
APP_PASSWORD = "請改成至少 16 字元的長密碼"
```

按下儲存並重新啟動 App。程式會從 Cloud Secrets 讀取密碼，實際密碼不會出現在 `app.py`、README 或 GitHub 儲存庫中。這個專案也已將 `.streamlit/secrets.toml` 列入 `.gitignore`。若日後想使用雜湊值，仍可使用 `generate_password_hash.py` 產生 `APP_PASSWORD_HASH`，但不是必要步驟。

共用密碼適合小規模分享，但它不是個人帳號系統；任何取得密碼的人都能使用服務。若需要逐一限制使用者，應改用 Google／Microsoft OIDC 或 Cloudflare Access。

## Streamlit Community Cloud 公開部署

1. 將本專案推送到 GitHub **私有儲存庫**，入口檔案選擇 `app.py`。
2. 在 Streamlit Community Cloud 以 GitHub 登入，建立新 App，選擇該儲存庫、分支與 `app.py`。
3. 開啟 App settings → Secrets，貼入 `APP_PASSWORD_HASH = "..."`。
4. 在 App settings → Sharing 設定可見性。若要讓任何持有網址及密碼的人使用，選擇公開分享；若只允許指定 Streamlit viewer，保留私有並加入指定 viewer。
5. Community Cloud 會提供 HTTPS 應用程式網址；不要額外把本機服務用 `0.0.0.0` 暴露出去，也不要把家用電腦當成公開伺服器。

公開分享並不等於不需要保護。請只把應用程式網址提供給需要的人，定期更換共用密碼，並在疑似外洩時立刻重新產生雜湊值與更新 Secrets。應用程式層的失敗鎖定是單一瀏覽器工作階段的基本防護，不能取代雲端 WAF、反向代理或完整的帳號系統。

## 啟動

啟動本機網站：

```bash
streamlit run app.py --server.address 127.0.0.1
```

啟動後，使用瀏覽器開啟 Streamlit 顯示的本機網址，通常是：

```text
http://127.0.0.1:8501
```

若在 Windows 上遇到 `python` 指令不可用，可改用：

```powershell
py -m pip install -r requirements.txt
py -m streamlit run app.py --server.address 127.0.0.1
```

## 使用方式

先將 PDF 或 DOCX 拖曳到上傳區域，也可以點擊上傳區域選擇檔案。確認檔案清單後，按下「開始提取圖片」。處理完成後可在結果區查看每個來源文件提取到的數量與預覽，最後按「下載全部圖片 ZIP」儲存結果。

本版本不支援舊版 `.doc`。如需處理舊版 Word 文件，請先用 Microsoft Word 或 LibreOffice 另存為 `.docx`，再上傳處理。

## 原始程式保留

`extract_images_original.py` 與 `extract_docx_images_original.py` 是你提供的原始版本備份。實際網站入口為 `app.py`，已將兩份程式的核心提取邏輯整合成可重用函式，並加入上傳、進度、結果預覽及 ZIP 下載流程。

## IP 與網路暴露說明

在本機使用下列啟動方式時，Streamlit 只綁定在 `127.0.0.1`，也就是本機回環介面。一般情況下，區域網路或網際網路上的其他人不能直接連到這個服務，因此不會因為這個程式本身而取得你的公開 IP。

需要特別注意以下情況：

| 情境 | 風險判斷 | 建議 |
|---|---|---|
| `--server.address 127.0.0.1`，只在自己的電腦開啟 | 低 | 建議使用此設定 |
| 綁定 `0.0.0.0` 或電腦區域網路 IP | 區域網路可嘗試連線 | 只在你明確需要其他裝置使用時採用，並設定防火牆 |
| 使用反向代理、雲端部署、公開隧道或分享服務 | 服務可能被公開；服務提供者可看到連線資訊 | 部署前先確認供應商的隱私與存取控制設定 |
| 在公司、學校或 VPN 網路中使用 | 網路管理者仍可能看到連線紀錄 | 這是網路環境層面的可見性，不是程式主動洩漏 |

本專案沒有加入文件外傳用的遙測、外部 API、遠端儲存或自動上傳功能。Streamlit Community Cloud 本身仍是第三方託管環境；文件會在該執行環境中處理，因此不要上傳不適合交給託管平台處理的高度機密文件。公開部署時已加入共用密碼、檔案大小限制與工作階段逾時，但若需要企業級存取控制，應使用 OIDC、Cloudflare Access 或其他具備個別身份管理的方案。

## 注意事項

PDF 圖片提取只會處理 PDF 內嵌的圖片物件，不會自動把整頁文字或向量圖形渲染成圖片。DOCX 提取則是取出文件封裝中的原始媒體檔案，因此某些瀏覽器無法預覽的格式仍然會正常放入 ZIP。

ZIP 會在目前工作階段於執行環境中建立。若文件內容敏感，請使用本機模式，並在處理完成後刪除下載檔與專案暫存資料夾。
