@echo off
REM The short command:  gmes run P1112UM00 --division VD --from 20260909 --to 20260909
REM It is only a shortcut for  python gmes_report.py  from this folder.
python "%~dp0gmes_report.py" %*
