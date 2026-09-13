# Enterprise system automation — N-ERP and G-MES

Windows/Chrome DevTools Protocol automation for two active Samsung systems:
N-ERP (SAP GUI for HTML) and G-MES (Nexacro). Both work against live
corporate systems; read [CLAUDE.md](CLAUDE.md) and [HISTORY.md](HISTORY.md)
before changing automation behavior.

## Current architecture

G-MES has one supported implementation: the flat root-level modules
`gmes_core.py`, `gmes_login.py`, `gmes_common.py`, `gmes_open_screen.py`,
`gmes_data.py`, `gmes_profile.py`, and their small callers. N-ERP remains
active and shares `cdp_common.py` with G-MES.

The former `src/gmes` standalone package was removed in HISTORY.md Phase 57.
It is recoverable only from Git history (`59eb838` or branch
`archive/standalone-gmes-before-removal`), not from a runnable directory in
this checkout. [CAPABILITY_RESCUE_MAP.md](CAPABILITY_RESCUE_MAP.md) records
the evidence-based disposition of every capability it contained.

## Setup

```powershell
python -m pip install -r requirements.txt
```

The only third-party dependency is `websocket-client`.

## G-MES

`GMES_Workflow.bat` is the primary Windows entrance:

```text
no arguments   -> python run_gmes_workflow.py
with arguments -> python gmes_report.py run %*
```

Both branches use only the supported flat modules and are guarded by
`tests/test_legacy_entrance.py`.

```powershell
python gmes_credentials.py set
.\GMES_Workflow.bat
python gmes_report.py run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
python gmes_open_screen.py --find "production"
python gmes_data.py forms
```

The active legacy credential store is
`%LOCALAPPDATA%\GMES_Automation\credentials.dat`. The donor package formerly
used `%LOCALAPPDATA%\GMES\credentials.dat`. Both are protected; no migration,
consolidation, inspection, or deletion is authorized.

## N-ERP

```powershell
python run_nerp_workflow.py MB52 "Material Number=SM-A137FLBHMEB" "Plant=P703"
python search_tcode.py MB51
python execute_filters.py "Plant=P703"
python export_to_excel.py MB51
```

## Offline checks

```powershell
python tests/test_unit.py
python tests/test_gmes_core.py
python tests/test_legacy_hardening.py
python tests/test_gmes_workflow.py
python tests/test_legacy_entrance.py
```

No test command above is authorization to use a live authenticated portal.
