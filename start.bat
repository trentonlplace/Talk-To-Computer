@echo off
title Talk To Computer
cd /d "%~dp0"

:: Kill only prior TTC instance via PID file
if exist .ttc.pid (
    set /p OLD_PID=<.ttc.pid
    tasklist /fi "PID eq %OLD_PID%" /fo csv /nh 2>nul | findstr /i "python" >nul
    if not errorlevel 1 (
        taskkill /f /pid %OLD_PID% >nul 2>&1
        echo Killed prior instance PID %OLD_PID%
    )
    del /f .ttc.pid >nul 2>&1
)
timeout /t 2 /nobreak >nul

:loop
echo Starting Talk To Computer...
venv\Scripts\python.exe -u main.py
if %errorlevel%==0 goto clean_exit
echo.
echo App crashed (exit code %errorlevel%). Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop

:clean_exit
echo App exited normally.
pause
