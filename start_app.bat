@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================================
echo Starting PDF Toolkit Web Server...
echo ============================================================

REM 1. Check if Ollama is running
curl -s -m 1 http://127.0.0.1:11434/api/tags >nul 2>&1
if not errorlevel 1 goto :OLLAMA_READY

echo [Ollama] Starting local Ollama server in background...
set "OLLAMA_BIN=ollama"
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_BIN=%ProgramFiles%\Ollama\ollama.exe"

start "" /min "%OLLAMA_BIN%" serve
ping 127.0.0.1 -n 3 >nul

:OLLAMA_READY
echo [Ollama] Local Ollama server is ready.

REM 2. Check required AI models (relative to repository root)
echo ============================================================
echo [Model Check] Verifying required local AI models...
echo ============================================================
if "%SKIP_MODEL_DOWNLOAD%"=="1" (
    echo [Model Check] SKIP_MODEL_DOWNLOAD=1 is set. Skipping model check and auto-download.
    goto :LAUNCH_SERVER
)

call :CHECK_ALL_MODELS
if "%MISSING_COUNT%"=="0" (
    echo [Model Check] All 4 required models are present.
    goto :LAUNCH_SERVER
)

echo.
echo [Model Check] %MISSING_COUNT% required model(s) missing.
echo [Model Check] Running src\scripts\model_manager.py to download/prepare missing models...

if defined PYTHONPATH goto :APPEND_PYTHONPATH
set "PYTHONPATH=%CD%"
goto :RUN_MODEL_MANAGER

:APPEND_PYTHONPATH
set "PYTHONPATH=%CD%;%PYTHONPATH%"

:RUN_MODEL_MANAGER
python "%~dp0src\scripts\model_manager.py"
set "MODEL_MANAGER_EXIT=%ERRORLEVEL%"
if not "%MODEL_MANAGER_EXIT%"=="0" (
    echo [WARNING] model_manager.py exited with code %MODEL_MANAGER_EXIT%.
)

echo.
echo [Model Check] Re-verifying required local AI models...
call :CHECK_ALL_MODELS
if "%MISSING_COUNT%"=="0" (
    echo [Model Check] All 4 required models are now ready.
    goto :LAUNCH_SERVER
)

echo.
echo [WARNING] %MISSING_COUNT% required model(s) are still missing after auto-download.
echo [WARNING] AI Formula / OCR features may be unavailable until those models are installed.
echo [WARNING] Continuing to launch PDF Toolkit Web Server for available tools...

:LAUNCH_SERVER
REM 3. Launch Web Server
echo ============================================================
echo Launching PDF Toolkit application...
echo ============================================================
python "%~dp0main.py" %*
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Web Server exited with code %APP_EXIT%
    pause
)
endlocal & exit /b %APP_EXIT%

REM ============================================================
REM Subroutines
REM ============================================================
:CHECK_ALL_MODELS
set "MISSING_COUNT=0"
call :CHECK_MODEL "models\pdf_extract_mfd.onnx" "Formula Stage 1 ONNX"
call :CHECK_MODEL "models\surya_det3\model.safetensors" "OCR Phase A text-line detection"
call :CHECK_MODEL "models\surya_rec2\model.safetensors" "Formula Stage 3 + OCR Phase B recognition"
call :CHECK_MODEL "models\surya_layout0\model.safetensors" "OCR Phase A layout analysis"
exit /b 0

:CHECK_MODEL
if not exist "%~1" goto :CHECK_MODEL_MISSING
echo [Model Check] [OK]      %~1 - %~2
exit /b 0

:CHECK_MODEL_MISSING
echo [Model Check] [MISSING] %~1 - %~2
set /a MISSING_COUNT+=1
exit /b 0
