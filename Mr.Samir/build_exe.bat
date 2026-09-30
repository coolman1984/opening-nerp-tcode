@echo off
REM Rebuild SamirExport.exe from the sources in app\ (needs Python and PyInstaller).
cd /d "%~dp0"

python app\sync_engine.py
if errorlevel 1 exit /b 1
python tests\test_samir.py
if errorlevel 1 (
    echo The tests failed - the .exe was NOT built.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed --name SamirExport ^
    --paths app --paths app\engine ^
    --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" ^
    app\samir_app.py
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo Built: %~dp0SamirExport.exe
python -c "import subprocess,sys; sys.exit(subprocess.call([r'%~dp0SamirExport.exe','--selftest']))"
