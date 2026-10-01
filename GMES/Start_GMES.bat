@echo off
REM GMES Automation - one-click launcher.
REM   Double-click this file. It starts GMES_Automation.exe when that file is next to it,
REM   otherwise it runs the same program with Python (app\gmes_app.py).
cd /d "%~dp0"

if exist "GMES_Automation.exe" (
    start "" "GMES_Automation.exe"
    exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: GMES_Automation.exe is not in this folder and Python was not found.
    echo Either copy GMES_Automation.exe next to this file, or install Python 3.
    pause
    exit /b 1
)

python -c "import websocket" >nul 2>&1
if errorlevel 1 (
    echo The 'websocket-client' package is missing. Install it once with:
    echo     python -m pip install websocket-client
    pause
    exit /b 1
)

where pythonw >nul 2>&1
if errorlevel 1 (
    python app\gmes_app.py
    if errorlevel 1 pause
) else (
    start "" pythonw app\gmes_app.py
)
