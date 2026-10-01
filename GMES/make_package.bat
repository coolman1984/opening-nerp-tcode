@echo off
REM Make GMES_Automation_package.zip: only what another person needs (no data\, no sources).
REM They unzip it anywhere and double-click Start_GMES.bat.
cd /d "%~dp0"
if not exist "GMES_Automation.exe" (
    echo GMES_Automation.exe is missing - run build_exe.bat first.
    pause
    exit /b 1
)
if exist "GMES_Automation_package.zip" del "GMES_Automation_package.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'Start_GMES.bat','GMES_Automation.exe','README.txt' -DestinationPath 'GMES_Automation_package.zip'"
if errorlevel 1 (
    echo Could not create the zip.
    pause
    exit /b 1
)
echo Created: %~dp0GMES_Automation_package.zip
