@echo off
REM Make GMES_Automation_package.zip: only what another person needs (no data\, no sources).
REM They unzip it anywhere and double-click Start_GMES.bat.
REM
REM   make_package.bat server   ->  GMES_Automation_server_package.zip, which also carries
REM   seed\: the recordings, saved batches and record checks of every G-MES site (SEEG and
REM   HQ), so a server starts knowing everything this PC proved. The window brings them in
REM   on its first start without replacing anything learned there (README.txt, "Server").
REM   Both zips carry WEEKLY_REPORTS.md (the weekly HQ reports guide) beside the program.
cd /d "%~dp0"
if not exist "GMES_Automation.exe" (
    echo GMES_Automation.exe is missing - run build_exe.bat first.
    pause
    exit /b 1
)
set "ZIP=GMES_Automation_package.zip"
set "ITEMS='Start_GMES.bat','GMES_Automation.exe','README.txt','app\shipped\WEEKLY_REPORTS.md'"
if /I "%~1"=="server" (
    python app\make_seed.py
    if errorlevel 1 (
        echo The seed could not be made - the zip was NOT created.
        pause
        exit /b 1
    )
    set "ZIP=GMES_Automation_server_package.zip"
    set "ITEMS='Start_GMES.bat','GMES_Automation.exe','README.txt','app\shipped\WEEKLY_REPORTS.md','seed'"
)
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path %ITEMS% -DestinationPath '%ZIP%'"
if errorlevel 1 (
    echo Could not create the zip.
    pause
    exit /b 1
)
echo Created: %~dp0%ZIP%
