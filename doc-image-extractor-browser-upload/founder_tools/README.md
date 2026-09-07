# 自動化校註系統 (Auto Footnote System) v2.0

這是一個專為古籍與學術排版設計的自動化校註注入工具。
具備「Zero-Unexplained Error」的嚴格校驗標準，支援自動化處理 Word 與 PDF 稿件，並將其轉出為統一的 DOCX 格式。

## 系統核心特點
1. **多標記支援**：支援提取 `①`、`〔1〕`、`[1]` 以及純數字 `1`。
2. **範本唯一真理**：所有產出之 Word 檔案，必定使用 `template.docx` 的樣式骨架，保證與後續方正排版軟體完美相容。
3. **無損樣式保留**：使用 Virtual Run Slicer 技術，切分腳註標記的同時，保留正文原有的粗體、斜體與特殊字型設定。
4. **方正字庫修復**：內建 PyMuPDF 整合的 `fix_founder_fonts.py`，自動修復 PDF 轉碼時發生的 CMap 彝文字母亂碼問題。
5. **Human Gate 人機協作**：絕不武斷猜測。未經人工覆核的低信心轉換將強制攔截，並進入彈窗審查。

## 目錄結構
- `自動化校註.bat`: 使用者雙擊啟動的捷徑。
- `template.docx`: 唯一真理骨架範本，內含 `af5` / `af7` 等樣式。
- `auto_footnote.py`: 總指揮引擎與命令列入口。
- `core/`: 存放註釋探勘 (Analyzer)、雙向匹配 (Matcher)、審計 (Auditor) 與 OpenXML 建構 (Builder) 的核心商業邏輯。
- `parsers/`: 負責解析原始 DOCX 或修復 PDF 內容的獨立模組。
- `ui/`: 存放 Tkinter 人機審核介面。

## 如何使用
1. 確認已安裝 Python 3。
2. 雙擊 `自動化校註.bat` 啟動圖形介面。
3. 選擇來源檔案 (`.docx` 或 `.pdf`)。
4. 點擊「開始分析與轉換」，系統將彈出 AI 探勘結果，供您覆核並選擇正確的標籤與標記設定。
5. 確認後系統將自動產出以 `template.docx` 為基底的修復後 Word 檔案。

## 依賴套件
```bash
pip install pymupdf
```
*(內建的 XML 解析已使用標準庫 xml.etree.ElementTree，無額外依賴)*
