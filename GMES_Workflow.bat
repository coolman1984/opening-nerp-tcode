@echo off
REM G-MES report workflow launcher - the command-line face of the tool whose window is
REM GMES\GMES_Automation.exe. Both are kept at the same level (CLAUDE.md section 0a).
REM   Double-click                        -> interactive prompts, pauses at the end.
REM   GMES_Workflow.bat P1112UM00 ...     -> passed straight to gmes_report.py run
REM   GMES_Workflow.bat record|check|status|confirm|forget|find|describe ...
REM                                       -> passed straight to gmes_report.py
REM   GMES_Workflow.bat sync|parity       -> gmes_twin.py (level with the window? its features)
REM   GMES_Workflow.bat rowexport ...     -> gmes_rowexport.py (one Excel per row of a list)
REM   GMES_Workflow.bat help|server|setup|verify|move-folder -> gmes_server.py (a server, ready?)
REM   GMES_Workflow.bat package ...       -> gmes_package.py (one folder + zip to move the tool)
REM   GMES_Workflow.bat help              -> every command on one screen
REM   GMES_Workflow.bat mcp [tools|call|config] -> gmes_mcp.py (AI agents: MCP server, JSON tools)
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    echo Install Python 3 from python.org, or run the scripts with a full path to python.exe.
    pause
    exit /b 1
)

REM The server and package commands come BEFORE the preflight: they are how a new
REM server finds out what is missing, so a failing preflight must not hide them.
set "GMES_COMMAND="
for %%C in (help server setup verify move-folder) do if /i "%~1"=="%%C" set "GMES_COMMAND=server"
if /i "%~1"=="package" set "GMES_COMMAND=package"
REM mcp comes before the preflight too: an MCP client reads this process's output as its
REM protocol, so nothing but the server may print (each tool runs the checks itself).
if /i "%~1"=="mcp" set "GMES_COMMAND=mcp"
if "%GMES_COMMAND%"=="server" goto :server
if "%GMES_COMMAND%"=="package" goto :package
if "%GMES_COMMAND%"=="mcp" goto :mcp

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

:server
python gmes_server.py %*
exit /b %ERRORLEVEL%

:package
python gmes_package.py %*
exit /b %ERRORLEVEL%

:mcp
python gmes_mcp.py %*
exit /b %ERRORLEVEL%
