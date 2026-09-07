@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ===================================================
echo   自動化校註系統 v2.0 (Zero-Unexplained Error)
echo ===================================================
echo.
echo [系統宣告]
echo 核心指導原則：「AI 負責理解來源，人工負責確認規則，程式負責精確執行。」
echo 輸出骨架綁定：本系統強制將最終產出之 XML 結構綁定為同目錄下的 template.docx
echo.
echo 正在啟動圖形介面...
python -m ui.gui_window %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [錯誤] 啟動失敗，請確認已安裝 Python 並滿足依賴套件。
    pause
)
