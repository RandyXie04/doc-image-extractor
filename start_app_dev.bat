@echo off
REM Developer launch script
cd /d "%~dp0"
set APP_MODE=dev
echo [Developer Mode] Starting PDF Toolkit with debug logs and dev tools enabled...
python app_window.py

