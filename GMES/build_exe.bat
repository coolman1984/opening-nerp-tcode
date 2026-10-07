@echo off
REM Rebuild GMES_Automation.exe from the sources in app\ (needs Python and PyInstaller).
cd /d "%~dp0"

REM A running GMES_Automation.exe cannot be replaced: PyInstaller then fails with a bare
REM "PermissionError: Access is denied" AFTER the whole build (HISTORY.md Phase 125).
tasklist /FI "IMAGENAME eq GMES_Automation.exe" /NH 2>nul | find /I "GMES_Automation.exe" >nul
if not errorlevel 1 (
    echo GMES Automation is running - close its window first ^(it ends by itself within a
    echo minute once the window is closed and nothing runs^), then build again.
    pause
    exit /b 1
)

python app\sync_engine.py
if errorlevel 1 exit /b 1
python tests\test_gmes_app.py
if errorlevel 1 (
    echo The tests failed - the .exe was NOT built.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed --name GMES_Automation ^
    --icon "%~dp0app\assets\gmes.ico" ^
    --add-data "%~dp0app\assets;assets" ^
    --add-data "%~dp0app\shipped;shipped" ^
    --add-data "%~dp0app\web;web" ^
    --paths "%~dp0app" --paths "%~dp0app\engine" ^
    --hidden-import web_server --hidden-import themes --hidden-import app_settings ^
    --hidden-import gmes_rowexport --hidden-import gmes_recordcheck --hidden-import gmes_twin ^
    --hidden-import account ^
    --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" ^
    "%~dp0app\gmes_app.py"
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo Built: %~dp0GMES_Automation.exe
