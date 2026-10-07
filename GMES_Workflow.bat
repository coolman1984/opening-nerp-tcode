@echo off
REM G-MES report workflow launcher - the command-line face of the tool whose window is
REM GMES\GMES_Automation.exe. Both are kept at the same level (CLAUDE.md section 0a).
REM   Double-click                        -> interactive prompts, pauses at the end.
REM   GMES_Workflow.bat P1112UM00 ...     -> passed straight to gmes_report.py run
REM   GMES_Workflow.bat record|check|status|confirm|forget|find|describe ...
REM                                       -> passed straight to gmes_report.py
REM   GMES_Workflow.bat sync|parity       -> gmes_twin.py (level with the window? its features)
REM   GMES_Workflow.bat rowexport ...     -> gmes_rowexport.py (one Excel per row of a list)
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    echo Install Python 3, or run the scripts with a full path to python.exe.
    pause
    exit /b 1
)

REM Read-only: Python version, websocket-client, a supported browser, and a
REM writable runtime directory - before the first real sign-in spends any of
REM the account's patience on a problem this could have caught instantly.
python gmes_preflight.py
if errorlevel 1 (
    pause
    exit /b 1
)

if "%~1"=="" (
    python run_gmes_workflow.py
    goto :eof
)

set "GMES_COMMAND="
for %%C in (record check status confirm forget find describe) do if /i "%~1"=="%%C" set "GMES_COMMAND=report"
for %%C in (sync parity) do if /i "%~1"=="%%C" set "GMES_COMMAND=twin"
if /i "%~1"=="rowexport" set "GMES_COMMAND=rowexport"
if "%GMES_COMMAND%"=="report" goto :report
if "%GMES_COMMAND%"=="twin" goto :twin
if "%GMES_COMMAND%"=="rowexport" goto :rowexport

python gmes_report.py run %*
exit /b %ERRORLEVEL%

:report
python gmes_report.py %*
exit /b %ERRORLEVEL%

:twin
python gmes_twin.py %*
exit /b %ERRORLEVEL%

:rowexport
python gmes_rowexport.py %*
exit /b %ERRORLEVEL%
