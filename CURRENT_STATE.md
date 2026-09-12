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
| 4 | Move `auth/` (credentials + login), credential-path migration | done — `auth/{credentials,login_flow,session}.py` ported; credential store resolves through `%LOCALAPPDATA%\GMES\credentials.dat`. Legacy copying is now only the explicit idempotent `gmes migrate` action; `gmes doctor` remains read-only. Folded the small `nexacro/{js_snippets,app_state,dom,popups}.py` subset and `application/connect_uc.py` forward from Phase 5/6 because login cannot be tested without them (see HISTORY.md Phase 31) |
| 5b | `screens/{filters,grids,organization,input_events,verification}.py` | done — date/filter matching, grid choice, org-tree ticking, key-event typing and Inquiry poll/verify ported from `gmes_core.py`, using `gmes.contracts` dataclasses instead of loose dicts. Pulled `query/{form_locator,dataset_reader,dataset_writer}.py` forward from 5d (unchanged, faithful port — the paging fix is still pending, landing as its own commit) and extended `nexacro/dom.py` with pattern-based `find_elements`/`click_control` (needed by `poll_inquiry` to find the Inquiry button, which has no stable full id), because 5b's own code cannot be tested without a working read path. `tests/unit/test_filters.py` and `tests/unit/test_grids.py` cover the pure-logic half (date/filter matching, grid choice); `tick_org`/`org_selection`/`type_text`/`poll_inquiry` have no offline test in either the old or new suite because they need a real browser (HISTORY.md Phase 14.9 — live-verified-only, unchanged by this move) |
| 5c | `discovery/{screen_discovery,screen,catalogue,fingerprint}.py` | done — `discover()`/`left_options()`/`org_trees()` now build `gmes.contracts` dataclasses directly from the JS_DISCOVER/JS_LEFT_OPTIONS/JS_ORG_TREES responses (the one real dict→dataclass construction point in the migration); the `Screen` class ported with all its methods rewritten onto typed attribute access, calling into `screens/grids.py`/`screens/organization.py` (Phase 5b) rather than inlining that logic; `catalogue.py` ported from `gmes_open_screen.py` (library functions only, no CLI); `fingerprint.py` ported from `gmes_profile.py`'s `fingerprint`/`describe_change` (its `field_ref`/`grid_ref`/`tree_ref`/`load`/`save` stay in `gmes_profile.py` for Phase 5f). **Deliberately deferred**: `Screen.export_excel()`/`to_csv()` are NOT yet on the ported class — they need `export/` (Phase 5e); nothing in the offline suite exercises them today (browser-only, HISTORY.md Phase 14.9), so no test gate is weakened by leaving them off until Phase 5e adds them back |
| 5d | Dataset paging fix in `query/dataset_reader.py` (`read_dataset_paged`) | done — `read_dataset_paged()` yields typed 300-row `DatasetPage` slices, advances by rows actually returned, and stops at the reported total or an empty page. `read_dataset(limit=-1)` drains those pages back into its existing dictionary result for `screens/verification.py`; positive bounded reads remain exactly one CDP call. `DatasetResult` is deliberately not wired yet because verification still relies on dictionary access. Offline paging tests cover a distinguishable 850-row dataset and an empty dataset. **Manual live comparison against a real 800–1500-row result remains outstanding.** |
| 5e | `export/{excel,csv_export,naming}.py` | done — `excel.py` faithfully preserves G-MES's same-WebSocket download configuration, target-then-Downloads fallback, polling and stable-size wait; NASCA DRM remains honestly delivery-only verification. `csv_export.py` streams `DatasetPage` values in page order, writes UTF-8 BOM, hides `_...` columns, and drops only completely empty public rows; it returns `ExportResult` for the later application layer. `naming.py` keeps only generic safe naming; report-specific conventions live outside G-MES. `Screen.export_excel()` and `to_csv()` are restored as delegations, with CSV using the discovered grid form/dataset. Offline tests cover all pure and delegated behaviour; no live Chrome/G-MES export or DRM-content verification was attempted. |
| 5f | `profiles/{refs,store,drift}.py` | done — standalone RECORD/REPLAY profiles now persist only allowlisted stable names under `%LOCALAPPDATA%\GMES\profiles\<CODE>.json`, not beside the executable. `refs.py` excludes coordinates, generated ids, dataset rows, tokens and credentials; `store.py` preserves malformed/missing-file safe handling, newest-first listing and non-destructive missing forget; `drift.py` reuses discovery's fingerprint comparison, preserves non-empty remembered values and recovers command values from older profiles. Offline tests use temporary LOCALAPPDATA only. **No live G-MES RECORD/REPLAY verification was attempted; that gap remains open.** |
| 6a | Application orchestration | done — typed sign-in attempts/retries and date parsing; generic RunSpec → RunResult pipeline with per-step verification, profile-drift refusal, checked exports and post-success memory; sequential batch isolation and summary. Generic G-MES has no report-specific policy; the Production Plan example is an external consumer. Legacy callers remain untouched. No live acceptance was attempted. |
| 6b | Unified CLI — initial command surface | done — `python -m gmes` and the package entry point dispatch offline `version`, typed `login`, sequential `run`, `data forms/read`, and explicit `migrate`; `data read` fixes the old limit drift with `--limit`. CLI reaches project behavior only through `application.facade`; remaining command families and workflow are pending |
| 6c | Architecture correction + Project Eye + early package smoke | done — CLI→application façade, data use case, externalized Production Plan policy, explicit credential migration, AST import rules, Project Eye map/rules, and PyInstaller onedir smoke before Phase 7 |
| 7 | Runtime state to `%LOCALAPPDATA%\GMES` (logs/screenshots/cache/config) | not started |
| 8 | `gmes doctor` | not started |
| 9 | Release-oriented PyInstaller onedir build (`dist/GMES/`) | not started — the early standalone smoke is already proved in Phase 6c; this later phase covers the complete command surface and release packaging |
| 10 | Offline + live regression pass (python -m gmes vs packaged exe) | not started |
| 11 | Prove standalone independence; retire old scripts | not started |

## Open gaps (tracked, not silently assumed closed)

- Phase 6a is offline-verified only: real SSO/direct fallback, notice timing,
  screen activation, filters, org/date confirmation, query settling, download
  dialogs, packaged profile replay and nightly content acceptance still need
  opt-in live verification. NASCA Excel content remains opaque to libraries.
- `sign_in()` now returns `LoginAttempt`, not a truthy success flag: callers
  must inspect `.outcome`. Retry waits use readiness observation; the old
  unconditional six-second pause was removed. Screenshots/log relocation is
  still Phase 7; CLI status/dispatch and session ownership remain later work.
- Latest offline gates after Phase 6c: N-ERP 31/31; standalone unit discovery
  209/209, including the architecture checkpoint. The PyInstaller onedir smoke runs
  `version` and `login`/`run`/`data` help from outside the repository with no
  Python executable on `PATH`; no live command is invoked.

- Windows 10 x64 hardware/VM verification — this dev machine is Windows 11
  Enterprise; Phase 9 can only prove the packaged exe runs standalone here.
- No full Nexacro mock exists or is planned; live-verified-only remains the
  gate for real CDP/Chrome/Nexacro runtime behavior (see `LESSONS.md` once
  written, and the plan's testing-strategy section).
