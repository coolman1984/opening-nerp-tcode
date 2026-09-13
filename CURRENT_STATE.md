# Migration state — G-MES standalone CLI

> ## ⚠️ THIS MIGRATION IS CANCELLED. `src/gmes` IS FROZEN.
>
> **Decided 2026-09-13 by the project owner.** Everything below documents a
> migration that will **not** be completed. It is retained as the record of
> what was built and what was proven, because the removal below has to be
> done layer by layer with evidence — not as a plan anyone should continue.
>
> **Do not tick another phase in this table. Do not add a phase. Do not
> "finish" anything listed here.**
>
> The production core is the flat legacy engine (`gmes_core.py`,
> `gmes_login.py`, `gmes_common.py`, `gmes_open_screen.py`, `cdp_common.py`
> and friends). See the banner in `ARCHITECTURE.md` for the full statement,
> the runtime hazard (shared CDP port 9444 and shared Chrome profile — never
> run both engines), and the archive branch.
>
> ### Restoration order (one step per commit, stop on any red test)
>
> | # | Step | Status |
> |---|---|---|
> | 1 | Archive branch `archive/standalone-gmes-before-removal` @ `59eb838` | **done** |
> | 2 | Rewrite the project rules to "Legacy primary / `src/gmes` frozen" (docs only) | **done — this commit** |
> | 3 | Restore `GMES_Workflow.bat` + `run_gmes_workflow.py` to the legacy implementation (source: `run_gmes_workflow_LEGACY_TEST.py`, not hand-rewritten); drop `PYTHONPATH=src` | **done** — restored from the git pins (`f23b776` launcher, `c6c7e8a` workflow) after proving the harness content-equivalent; no args → `run_gmes_workflow.py`, with args → `gmes_report.py run`; import-proved to load zero `gmes.*` modules. N-ERP 32, legacy core 56, legacy hardening 9 all pass. One test left deliberately failing for step 4 (HISTORY.md 57.4) |
> | 4 | Restore the legacy workflow tests; add a guard test proving the legacy entrance loads **zero** `gmes.*` modules; `tests/test_gmes_core.py` and all N-ERP tests stay green | **done** — both historical workflow test files restored from `c6c7e8a` (the obsolete bridge assertion removed); new `tests/test_legacy_entrance.py` adds 7 guards covering **both** launcher branches, with import isolation proved in a fresh subprocess and the `.bat` matched case-insensitively. Supported path green: N-ERP 32, legacy core 56, hardening 9, workflow 2, guards 7 = **106, zero failures** (HISTORY.md 57.5) |
> | 4.5 | **Capability Rescue Map** — classify every `src/gmes` capability KEEP / REBUILD SMALL / DISCARD before anything is deleted (docs only) | **done** — [CAPABILITY_RESCUE_MAP.md](CAPABILITY_RESCUE_MAP.md), 14 capabilities classified with problem, files, tests, live-proof status, coupling, smallest legacy reproduction and the regression evidence that must survive. Found two live-proven fixes that exist ONLY in the frozen package and whose absence makes the legacy core worse **today** (HISTORY.md 57.6) |
> | **E1** | **Port `--disable-popup-blocking` into `cdp_common.py`** — a confirmed capability gap in the legacy launcher, not yet a direct live failure proof on the legacy path itself; live-proven necessary against the frozen engine's identical launch pattern (56.1). N-ERP suite gates it (shared file) | **done** — added to `launch_chrome_with_user_profile()`'s argument list, same position as the proven fix; 2 new regression tests in `tests/test_unit.py` (mocked, no live browser); N-ERP 34/34, legacy core 56/56, hardening 9/9, workflow 2/2, entrance guards 7/7 — zero regressions (HISTORY.md 57.7). **Not yet live-tested on the legacy path.** |
> | **E2** | **Port the screenshot-target fix** to the G-MES path; do NOT change `get_page_tab`'s `"nerps"` default | **done** — `capture_screenshot()`/`screenshot_on_failure()` gained an optional `tab=` override (default unset, N-ERP unaffected); a new `gmes_common.capture_screenshot()`/`screenshot_on_failure()` wrapper resolves the correct tab via `gmes_tab()`'s already-proven host matching (not a raw substring - the ADFS popup's own URL carries the G-MES hostname text inside its RelayState param, so a naive substring match would have reintroduced the collision). Wired into the supported entrance chain (`gmes_login.py`, `gmes_core.py`, `gmes_open_screen.py`, `gmes_daily_prodplan.py`); `gmes_connect.py` and the read-only probe tools deliberately left untouched (outside the supported entrance; `gmes_connect.py` does not import `gmes_common`). 7 new tests, no browser launched. Supported path still green (HISTORY.md 57.8). |
> | 5 | Close the new engine's doors (`gmes.bat` first). Nothing deleted yet | not started — see the extraction order E1–E10 in the rescue map; E1/E2 come first |
> | 6 | Keep the runtime isolated — do not run the new engine at all; do not move or "clean" the legacy Chrome profile, protect it | not started |
> | 7 | Remove `src/gmes` from the outside in: packaging/`pyproject.toml`/standalone launchers, then resilience-only modules, then CLI/application, then the rest. Run legacy + N-ERP regression after **each** layer | not started |
> | 8 | Delete `src/gmes` entirely, only after a repo-wide import/reference scan proves nothing depends on it | not started |
>
> **Not by `git revert`.** The standalone work began as a scaffold in
> `67117e5` and was built up over many commits, with useful legacy fixes
> landing in between. A broad revert would take those fixes out with it.
> Controlled manual dismantling only.

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
| 5b | `screens/{filters,grids,organization,input_events,verification}.py` | done — date/filter matching, grid choice, org-tree ticking, key-event typing and Inquiry poll/verify ported from `gmes_core.py`, using `gmes.contracts` dataclasses instead of loose dicts. The accompanying read path is paged in Phase 5d; `nexacro/dom.py` supplies pattern-based `find_elements`/`click_control` for Inquiry controls without stable ids. `tests/unit/test_filters.py` and `tests/unit/test_grids.py` cover the pure-logic half; browser-driven controls remain live-verified-only. |
| 5c | `discovery/{screen_discovery,screen,catalogue,fingerprint}.py` | done — `discover()`/`left_options()`/`org_trees()` now build `gmes.contracts` dataclasses directly from the JS_DISCOVER/JS_LEFT_OPTIONS/JS_ORG_TREES responses (the one real dict→dataclass construction point in the migration); the `Screen` class ported with all its methods rewritten onto typed attribute access, calling into `screens/grids.py`/`screens/organization.py` (Phase 5b) rather than inlining that logic; `catalogue.py` ported from `gmes_open_screen.py` (library functions only, no CLI); `fingerprint.py` ported from `gmes_profile.py`'s `fingerprint`/`describe_change` (its `field_ref`/`grid_ref`/`tree_ref`/`load`/`save` stay in `gmes_profile.py` for Phase 5f). **Deliberately deferred**: `Screen.export_excel()`/`to_csv()` are NOT yet on the ported class — they need `export/` (Phase 5e); nothing in the offline suite exercises them today (browser-only, HISTORY.md Phase 14.9), so no test gate is weakened by leaving them off until Phase 5e adds them back |
| 5d | Dataset paging fix in `query/dataset_reader.py` (`read_dataset_paged`) | done — `read_dataset_paged()` yields typed 300-row `DatasetPage` slices, advances by rows actually returned, and stops at the reported total or an empty page. `read_dataset(limit=-1)` drains those pages back into its existing dictionary result for `screens/verification.py`; positive bounded reads remain exactly one CDP call. `DatasetResult` is deliberately not wired yet because verification still relies on dictionary access. Offline paging tests cover a distinguishable 850-row dataset and an empty dataset. **Manual live comparison against a real 800–1500-row result remains outstanding.** |
| 5e | `export/{excel,csv_export,naming}.py` | done — `excel.py` faithfully preserves G-MES's same-WebSocket download configuration, target-then-Downloads fallback, polling and stable-size wait; NASCA DRM remains honestly delivery-only verification. `csv_export.py` streams `DatasetPage` values in page order, writes UTF-8 BOM, hides `_...` columns, and drops only completely empty public rows; it returns `ExportResult` for the later application layer. `naming.py` keeps only generic safe naming; report-specific conventions live outside G-MES. `Screen.export_excel()` and `to_csv()` are restored as delegations, with CSV using the discovered grid form/dataset. Offline tests cover all pure and delegated behaviour; no live Chrome/G-MES export or DRM-content verification was attempted. |
| 5f | `profiles/{refs,store,drift}.py` | done — standalone RECORD/REPLAY profiles now persist only allowlisted stable names under `%LOCALAPPDATA%\GMES\profiles\<CODE>.json`, not beside the executable. `refs.py` excludes coordinates, generated ids, dataset rows, tokens and credentials; `store.py` preserves malformed/missing-file safe handling, newest-first listing and non-destructive missing forget; `drift.py` reuses discovery's fingerprint comparison, preserves non-empty remembered values and recovers command values from older profiles. Offline tests use temporary LOCALAPPDATA only. **No live G-MES RECORD/REPLAY verification was attempted; that gap remains open.** |
| 6a | Application orchestration | done — typed sign-in attempts/retries and date parsing; generic RunSpec → RunResult pipeline with per-step verification, profile-drift refusal, checked exports and post-success memory; sequential batch isolation and summary. Generic G-MES has no report-specific policy; the Production Plan example is an external consumer. Legacy callers remain untouched. No live acceptance was attempted. |
| 6b | Unified CLI — command and guided workflow surface | done — `python -m gmes` dispatches `version`, typed `login`, `credentials set`, sequential `run`, `data forms/read`, explicit `migrate`, `doctor`, and `workflow`. CLI reaches project behavior only through `application.facade`; the guided workflow is the compatibility entrance used by the historical filename and `.bat` launcher. |
| 6c | Architecture correction + Project Eye + early package smoke | done — CLI→application façade, data use case, externalized Production Plan policy, explicit credential migration, AST import rules, Project Eye map/rules, and PyInstaller onedir smoke before Phase 7 |
| 6d | Runtime-boundary correction | done — high-level application operations now own sign-in, CDP acquire/use/release, and typed outcomes; CLI only parses, invokes one operation, renders, and exits. Specialized recipes receive data pages through a public capability, never a socket. Architecture checks enforce this across every CLI file and external consumer. |
| 7 | Runtime state to `%LOCALAPPDATA%\GMES` (logs/screenshots/cache/config) | done — credentials, profiles, logs, screenshots, evidence, config/cache paths and implicit exports resolve through `paths.py`; application logging is redacted and flushes live evidence. The established Chrome-owned copy of the user’s Default profile remains at `%LOCALAPPDATA%\Google\Chrome\CDP Profile` by explicit user requirement and is never the real profile. |
| 8 | `gmes doctor` | done — public read-only doctor reports Windows, package mode, dependency, Chrome, CDP/proxy, standalone runtime paths, credential presence, profile JSON health, and profile-copy staleness. It neither creates state nor migrates/repairs anything. `gmes credentials set` is the separate explicit DPAPI replacement path. |
| 9 | Release-oriented PyInstaller onedir build (`dist/GMES/`) | done — current `dist\GMES\GMES.exe` rebuilt cleanly and copied to a temporary directory outside the repository. With Python removed from `PATH`, frozen `version` and `doctor` ran and `login`/`run`/`data`/`migrate`/`credentials set` help succeeded. The build limits optional OpenBLAS hook discovery to one thread after an unrelated PyInstaller allocation failure. |
| 10 | Offline + live regression pass (python -m gmes vs packaged exe) | partially unblocked 2026-09-12 — against an already-authenticated real G-MES session (not through `gmes login` itself), `gmes doctor`, `data forms`, `data read`, `run --dry-run` and now a full non-dry-run `run` (P1112UM00, division VD, dated range, 6815 rows in 30.5s, profile learned) all succeeded live; two real bugs found/fixed (HISTORY.md Phase 41). Export (`xlsx`/`csv`) and the packaged exe's live journey remain unattempted. |
| 11 | One execution engine with compatible entrances | done offline — `GMES_Workflow.bat` opens the guided `gmes workflow` command, `run_gmes_workflow.py` is a zero-logic bridge to that same command, and argument-bearing `.bat` calls still reach `gmes run`. All supported everyday entrances now use `src/gmes → application.facade`; flat runners remain comparison-only and must not receive new behaviour. |

| 12 | Choices read from the live screen, and notices that actually close | done offline — the guided workflow opens the screen before it asks anything and lists every filter (name + current value), every left-panel option with its state, the tickable divisions and the Quick View screens; picks are made by number or name. Notices are closed at screen open, before Inquiry and before the Excel icon, with Nexacro's own `ChildFrame.close()` as the fallback when the X does not land, and anything unidentifiable is reported rather than clicked. The Excel export retries three times, re-focusing and clearing the screen each attempt (HISTORY.md Phase 45). **Not yet exercised against live G-MES.** |

| 13 | Unattended recovery ladder | done offline — each screen runs through `application/recovery.py`: reattach + clear notices, then prune both caches and reload, then close and restart the automation browser and sign in again, then stop with the last real reason. Bounded by a wall-clock budget and a cold-start limit. This project's own refusals (ambiguous grid, no matching filter, zero rows) are classified as decisions and never retried. The cold start never refreshes the profile (CLAUDE.md 2.1a), asserted by test. **Not yet exercised against live G-MES.** |

| 14 | Runs on a second machine | done offline — `automation_profile()` keeps the developer's existing profile copy in use where it exists and gives every other machine a clean program-owned profile that is never copied into; `find_browser()` falls back to Edge where Chrome is absent; `auth/install.py` tells a first run apart from an inherited tree and `onboarding_uc` asks that person for their own login, but only when a console is attached so the nightly job can never hang at a password box. Nothing is deleted on a mismatch (CLAUDE.md 2.1a). **Not yet exercised on a real second machine.** |

| 15 | Record/replay round trip | done offline — the screen shape is recorded from the screen AS OPENED, the same state the next run compares it against; the drift check is split so the shape is verified before anything is clicked and the saved references after the saved options have rebuilt the panel. This fixes a screen recorded with a left-panel option never being replayable. `--relearn` (and `r` in the guided workflow) records a drifted screen again instead of dead-ending. **Not yet exercised against live G-MES.** |

| 16 | Browser/profile fallback ladder | done offline — `launch_chrome_with_user_profile()` tries an ordered list of browser/profile combinations (the chosen strategy, then a clean profile if different, then Edge) instead of one, terminating a failed attempt before the next is tried. An explicit profile refresh is never silently substituted for a different combination. **Not yet exercised against a real corrupted profile or missing Chrome install.** |

| 17 | Circuit breaker for chronically broken screens | done offline — `application/circuit.py` persists a per-screen consecutive-failure count; after 3 in a row the screen is skipped before the browser is touched (the batch continues to the next screen, unlike a genuine mid-run failure which still stops it), and `--force` (or `f`/`r` in the guided workflow) tries anyway. Any success closes it outright. **Not yet exercised against a real chronically-broken screen.** |

| 18 | Batch checkpoint/resume across a full process crash | done offline — `application/checkpoint.py` records a real success keyed by a digest of what the batch asks for (never what it proves); the next identical `gmes run` skips only already-succeeded screens and resumes the rest, `--fresh` bypasses it, and a record older than 6 hours or from a different batch is ignored outright. **Not yet exercised against a real interrupted process.** |

| 19 | External watchdog for a genuine hang | done offline — `application/heartbeat.py` records liveness at sign-in-attempt, per-screen, and per-recovery-rung granularity; `application/supervisor_uc.py` (`gmes supervise <command>`) runs it as a child process and kills+restarts (once, by default) only on total silence past a generous window, never on an ordinary failure or exit code. Kills by PID/tree, never `taskkill /IM chrome.exe` (CLAUDE.md 2.6). **Not yet exercised against a real hang.** |

| 20 | Failure alerting | done offline — `application/alerts.py` sends one best-effort email via stdlib smtplib when a batch does not fully succeed (never on success); GMES_ALERT_HOST/TO/FROM/PORT are environment variables, but the SMTP login is a separate DPAPI secret (`gmes credentials set-alert-smtp`), never an environment variable. Wired into `execute_run` so both `gmes run` and `gmes supervise run` get it; the supervisor also sends its own alert when it kills a stuck process, since that process never reaches its own alert call. **Not yet exercised against a real mail server.** |
| 21 | Pre-merge review fixes (Phase 54) | done offline — fixed six defects a review found in Phases 46-53 before merge: the watchdog could not detect a hang before the first heartbeat; its own test mocked the wrong scenario; a killed process had no way to alert anyone; STARTTLS was checked before EHLO and never actually engaged; the alert SMTP password lived in a plain environment variable; the circuit breaker could trip on this project's own deliberate refusals (bad filter values) rather than only genuine faults; a resumed checkpoint trusted a file without checking it still exists on disk. See HISTORY.md Phase 54 for each. |
| 22 | Second review pass (Phase 55) | done offline — a saved SMTP login could still be sent over a plaintext connection when the server offered no STARTTLS (detecting encryption and acting on it were two different, previously disconnected steps); the heartbeat file was a single shared path for every supervised run on the machine, so two at once could read or clear each other's liveness signal. Both fixed: notify() refuses to send a saved credential unencrypted, and heartbeat_path() is now scoped per process id. See HISTORY.md Phase 55. |

## Open gaps (tracked, not silently assumed closed)

- `gmes login` itself remains unverified against a real credential: the
  2026-09-12 live testing above reused an already-authenticated session
  (CDP found a signed-in Chrome already running) rather than exercising the
  standalone sign-in flow end to end. A valid already-authorized session or
  corrected credential is still required before `login`, export, paging,
  profile, source/package parity, or a three-run live claim can be made.
- The same 2026-09-12 session, working against that already-signed-in
  browser, live-verified `doctor`, `data forms`, `data read`,
  `run --dry-run` (screen open/activate, filter/grid discovery), and then a
  full non-dry-run `run` for the first time — `gmes run P1112UM00 --division
  VD --from 20260901 --to 20260912 --export none` returned 6815 rows in
  30.5s, correctly resolved an ambiguous "VD" category tree match, and
  learned a profile. Found and fixed two real bugs neither offline suite had
  caught (HISTORY.md Phase 41; GMES_SKILL.md gotcha #47). Export (`xlsx`/
  `csv`) was deliberately not exercised yet - it pulls real production data
  to local disk and was left for an explicit opt-in.
- Phase 6a is otherwise offline-verified only: real SSO/direct fallback, notice timing,
  screen activation, filters, org/date confirmation, query settling, download
  dialogs, packaged profile replay and nightly content acceptance still need
  opt-in live verification. NASCA Excel content remains opaque to libraries.
- `sign_in()` returns `LoginAttempt`, not a truthy success flag. Runtime
  operations own all CDP acquire/use/release and return typed execution results.
  Retry waits use readiness observation; the old unconditional six-second pause
  was removed. A direct post-navigation fixed delay was also removed; named
  tab polling is the readiness condition. Latest offline gates after Phase 42:
  N-ERP 31/31; standalone unit discovery 243 tests (2 Windows-only DPAPI checks skipped), including architecture and
  doctor read-only checks. The PyInstaller onedir smoke runs frozen `version`
  and `doctor`, plus `login`/`run`/`data`/`migrate`/`credentials set` help, outside the
  repository with no Python executable on `PATH`; no package live command was invoked.

- Windows 10 x64 hardware/VM verification — this dev machine is Windows 11
  Enterprise; Phase 9 can only prove the packaged exe runs standalone here.
- No full Nexacro mock exists or is planned; live-verified-only remains the
  gate for real CDP/Chrome/Nexacro runtime behavior (see `LESSONS.md` once
  written, and the plan's testing-strategy section).
