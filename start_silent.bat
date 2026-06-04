@echo off
set APPDIR=C:\Users\Administrator\.sentineldesk
set LOG=%APPDIR%\logs\server.log
set PY=C:\Program Files\Python312\pythonw.exe

REM Prevent multiple instances
tasklist /FI "IMAGENAME eq pythonw.exe" /FI "WINDOWTITLE eq RDVR" 2>NUL | find /I "pythonw.exe" >NUL
if %ERRORLEVEL%==0 (
    echo RDVR is already running.
    exit /b 0
)

REM Start silently in background with output redirected to log
cd /d "%APPDIR%"
start "RDVR" /MIN "%PY%" -u "%APPDIR%\app.py" >> "%LOG%" 2>&1

echo RDVR started silently. Log: %LOG%
