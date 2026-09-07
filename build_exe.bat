@echo off
REM PyInstaller build script for PDF Toolkit
setlocal enabledelayedexpansion

cd /d "%~dp0"
echo [1/3] Cleaning previous build artifacts...
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"

echo [2/3] Building executable with PyInstaller...
python -m PyInstaller --clean build_app.spec

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Build failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo [3/3] Build completed successfully!
echo Output folder: dist\PDF_Toolkit\
echo Main executable: dist\PDF_Toolkit\PDF_Toolkit.exe
exit /b 0
