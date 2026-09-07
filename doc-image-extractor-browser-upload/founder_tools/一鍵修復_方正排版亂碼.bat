@echo off
chcp 65001 >nul
title 方正排版 (Founder Fonts) 標點符號一鍵修復工具

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if "%~1"=="" (
    python fix_founder_fonts.py
) else (
    echo [INFO] 正在處理拖曳進來的檔案/資料夾: %1
    python fix_founder_fonts.py "%~1"
    pause
)
