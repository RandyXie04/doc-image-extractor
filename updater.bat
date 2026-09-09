@echo off
REM updater.bat
REM Usage: updater.bat <PID> <OLD_EXE> <NEW_EXE>

set PID=%1
set OLD_EXE=%2
set NEW_EXE=%3

echo [Updater] Waiting for process %PID% to exit...

:WAIT_LOOP
tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >NUL
    goto WAIT_LOOP
)

echo [Updater] Process %PID% ended.
echo [Updater] Replacing %OLD_EXE% with %NEW_EXE%...

move /y %NEW_EXE% %OLD_EXE%

if "%ERRORLEVEL%"=="0" (
    echo [Updater] Update successful! Starting new version...
    start "" %OLD_EXE%
) else (
    echo [Updater] Update failed!
    pause
)

exit /b 0
