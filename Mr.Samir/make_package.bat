@echo off
REM Make Mr.Samir_package.zip: only what another person needs (no data\ folder, no sources).
REM Send that zip; they unzip it anywhere and double-click Start_Samir.bat.
cd /d "%~dp0"
if not exist "SamirExport.exe" (
    echo SamirExport.exe is missing - run build_exe.bat first.
    pause
    exit /b 1
)
if exist "Mr.Samir_package.zip" del "Mr.Samir_package.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'Start_Samir.bat','SamirExport.exe','README.txt' -DestinationPath 'Mr.Samir_package.zip'"
if errorlevel 1 (
    echo Could not create the zip.
    pause
    exit /b 1
)
echo Created: %~dp0Mr.Samir_package.zip
