@echo off
cd /d "%~dp0"
if "%~1"=="" (
    python run_nerp_workflow.py
    pause
    goto :eof
)
python run_nerp_workflow.py %*
exit /b %ERRORLEVEL%
