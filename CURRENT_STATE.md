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
| 2 | `contracts/` + `paths.py` (with migration-detection helper) | not started |
| 3 | Fork the browser layer into `browser/*.py` | not started |
| 4 | Move `auth/` (credentials + login), credential-path migration | not started |
| 5 | Move the bulk of `gmes_core.py` (nexacro/screens/discovery/query/export/profiles); apply the dataset-paging fix | not started |
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
