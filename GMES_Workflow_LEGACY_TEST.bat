@echo off
REM ===========================================================================
REM  LEGACY COMPARISON HARNESS - not the supported entrance, not a rollback.
REM
REM  Runs the TRUE pre-unification G-MES engine, restored verbatim from commit
REM  c6c7e8a ("Harden legacy GMES workflow safety") - the last commit before
REM  07b5a8d ("Unify G-MES legacy and standalone workflow") replaced
REM  run_gmes_workflow.py's 649 lines with a 24-line bridge into src/gmes.
REM
REM  Proven call chain (HISTORY.md Phase 56.5):
REM    GMES_Workflow_LEGACY_TEST.bat
REM      -> run_gmes_workflow_LEGACY_TEST.py   (verbatim legacy, 649 lines)
REM         -> cdp_common.py  gmes_core.py  gmes_log.py
REM            gmes_open_screen.py  gmes_profile.py  gmes_ui.py
REM         -> gmes_core.sign_in() -> gmes_login.main() -> gmes_credentials.py
REM    ...with ZERO imports from src/gmes.
REM
REM  PYTHONPATH is deliberately NOT pointed at .\src, so the new engine cannot
REM  be reached even by accident. Every current file is preserved untouched.
REM
REM  WARNING: the legacy engine contains the SAME automatic password fallback
REM  as the new one (gmes_login.main(): "AD SSO did not complete. Signing in
REM  with the saved credentials on G-MES's own form..."), and reads a
REM  credential store byte-identical to the new one. Running it live WILL
REM  spend a real login attempt against the account's 5-try lockout.
REM ===========================================================================
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    pause
    exit /b 1
)

REM No "set PYTHONPATH=%~dp0src" here, on purpose - see the header.
python run_gmes_workflow_LEGACY_TEST.py %*
exit /b %ERRORLEVEL%
