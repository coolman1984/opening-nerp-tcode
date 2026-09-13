@echo off
REM G-MES standalone CLI launcher.
REM   GMES_Workflow.bat run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    echo Install Python 3, or run the scripts with a full path to python.exe.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
if "%~1"=="" (
    python -m gmes --help
    pause
    goto :eof
)

python -m gmes %*
exit /b %ERRORLEVEL%
