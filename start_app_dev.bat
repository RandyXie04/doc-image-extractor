@echo off
REM PDF Toolkit - Developer Mode Launcher
cd /d "%~dp0"
set APP_MODE=dev
echo ============================================================
echo Starting PDF Toolkit in Developer Mode...
echo ============================================================
python "%~dp0main.py" --dev
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Web Server exited with code %ERRORLEVEL%
    pause
)
