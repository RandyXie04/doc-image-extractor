@echo off
cd /d "%~dp0"

echo ============================================================
echo Starting PDF Toolkit Web Server...
echo ============================================================

REM 1. Check if Ollama is running
curl -s -m 1 http://127.0.0.1:11434/api/tags >nul 2>&1
if not errorlevel 1 goto OLLAMA_READY

echo [Ollama] Starting local Ollama server in background...
set "OLLAMA_BIN=ollama"
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_BIN=%ProgramFiles%\Ollama\ollama.exe"

start "" /min "%OLLAMA_BIN%" serve
ping 127.0.0.1 -n 3 >nul

:OLLAMA_READY
echo [Ollama] Local Ollama server is ready.

REM 2. Launch Web Server
echo ============================================================
echo Launching PDF Toolkit application...
echo ============================================================
python "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Web Server exited with code %ERRORLEVEL%
    pause
)
