# Migration state — G-MES standalone CLI

Living doc: updated at the end of every phase. See `ARCHITECTURE.md` for the
target shape and the approved migration plan for full phase rationale.

## Phase 0 — scaffolding created (src/gmes/ tree, pyproject.toml, no code moved yet)
2026-09-12

## Phases

| # | Phase | Status |
|---|---|---|
| 0 | Scaffold `src/gmes/` tree + `pyproject.toml` | done |
| 1 | Freeze existing tests under `tests/unit/`; pin `gmes_data` argv bug | done — 56+2 tests copied unchanged (still importing old flat modules); 3 new tests added pinning the `read` command's `argv[4]`-vs-`argv[3]` limit bug and confirming the `csv` command's output-path arg is unaffected |
| 2 | `contracts/` + `paths.py` (with migration-detection helper) | done — 5 contract modules (screen/login/run/profile/dataset) as frozen dataclasses matching the real dict/JSON shapes field-for-field; `paths.py` resolves `%LOCALAPPDATA%\GMES` and does a non-destructive one-time copy-migration from the legacy `GMES_Automation` credential path. Neither wired to any real command yet |
| 3 | Fork the browser layer into `browser/*.py` | done — 19 functions/constants forked into `cdp.py`/`chrome.py`/`interaction.py`/`screenshots.py`, corrected against the real `cdp_common` call graph (grep found `get_page_tab` IS needed by G-MES, despite looking N-ERP-only; found `launch_chrome`/`profile_dir`/`connect_with_retry`/the SAP-specific text/dialog/busy-wait helpers are NOT). No `waits.py` — nothing generic to fork there. `cdp_common.py` itself untouched; parity test (8 tests) pins signatures against the original |
| 4 | Move `auth/` (credentials + login), credential-path migration | done — `auth/{credentials,login_flow,session}.py` ported; credential store now resolves through `%LOCALAPPDATA%\GMES\credentials.dat` (same DPAPI entropy, so old stores stay readable — migration copy is `gmes doctor`'s job, built in Phase 2, not yet wired to a command). Folded the small `nexacro/{js_snippets,app_state,dom,popups}.py` subset and `application/connect_uc.py` forward from Phase 5/6 because login cannot be tested without them (see HISTORY.md Phase 31) |
| 5 | Move the rest of `gmes_core.py` (discovery/screens/query/export/profiles, plus the remaining nexacro/ shape-based lookups); apply the dataset-paging fix | not started — the sign-in-only subset of nexacro/ and application/ already exists per Phase 4 above |
| 6 | Build `application/*_uc.py` + the unified CLI | not started |
| 7 | Runtime state to `%LOCALAPPDATA%\GMES` (logs/screenshots/cache/config) | not started |
| 8 | `gmes doctor` | not started |
| 9 | PyInstaller onedir build (`dist/GMES/`) | not started |
| 10 | Offline + live regression pass (python -m gmes vs packaged exe) | not started |
| 11 | Prove standalone independence; retire old scripts | not started |

## Open gaps (tracked, not silently assumed closed)

- Windows 10 x64 hardware/VM verification — this dev machine is Windows 11
  Enterprise; Phase 9 can only prove the packaged exe runs standalone here.
- No full Nexacro mock exists or is planned; live-verified-only remains the
  gate for real CDP/Chrome/Nexacro runtime behavior (see `LESSONS.md` once
  written, and the plan's testing-strategy section).
