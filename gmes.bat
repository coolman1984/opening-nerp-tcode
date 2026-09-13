@echo off
REM The only supported source command for standalone G-MES.
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m gmes %*
