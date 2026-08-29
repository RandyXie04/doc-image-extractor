@echo off
rem =========================================================================
rem PDF Formula Extractor Launcher (MFD AI)
rem Directly launches the integrated GUI tool without a console window.
rem =========================================================================

cd /d "%~dp0"
start "" pythonw scripts\run.py
