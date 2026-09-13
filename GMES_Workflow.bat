@echo off
REM G-MES report workflow launcher.
REM   Double-click                        -> interactive prompts, pauses at the end.
REM   GMES_Workflow.bat P1112UM00 ...     -> passed straight to gmes_report.py run
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    echo Install Python 3, or run the scripts with a full path to python.exe.
    pause
    exit /b 1
)

if "%~1"=="" (
    python run_gmes_workflow.py
    goto :eof
)

python gmes_report.py run %*
exit /b %ERRORLEVEL%
