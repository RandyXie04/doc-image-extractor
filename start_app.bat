@echo off
REM PDF Toolkit - Web Server Launcher
cd /d "%~dp0"
echo ============================================================
echo Starting PDF Toolkit Web Server...
echo ============================================================
python "%~dp0main.py"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Web Server exited with code %ERRORLEVEL%
    pause
)
