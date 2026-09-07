@echo off
cd /d "%~dp0"
echo Starting PDF Toolkit...
python app_window.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Application exited with code %ERRORLEVEL%
    pause
)
