@echo off
REM Samir Export - one-click launcher.
REM   Double-click this file.  It starts SamirExport.exe when that file is next to it,
REM   otherwise it runs the same program with Python (app\samir_app.py).
cd /d "%~dp0"

if exist "SamirExport.exe" (
    start "" "SamirExport.exe"
    exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: SamirExport.exe is not in this folder and Python was not found.
    echo Either copy SamirExport.exe next to this file, or install Python 3.
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
    python app\samir_app.py
    if errorlevel 1 pause
) else (
    start "" pythonw app\samir_app.py
)
