@echo off
REM NERP T-code workflow launcher.
REM   Double-click            -> interactive prompts, pauses at the end.
REM   NERP_Workflow.bat MB52 "Plant=P703"   -> non-interactive, no pause.
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    echo Install Python 3, or run the scripts with a full path to python.exe.
    pause
    exit /b 1
)

if "%~1"=="" (
    python run_nerp_workflow.py
    pause
    goto :eof
)

python run_nerp_workflow.py %*
exit /b %ERRORLEVEL%
