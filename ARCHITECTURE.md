# G-MES standalone CLI — architecture

Living reference for the `gmes.exe` migration. See the approved migration
plan (kept by the user) for full phase-by-phase detail and rationale; this
file tracks the *target* shape as it is actually built, and should be
updated whenever a phase in `CURRENT_STATE.md` lands.

N-ERP (`cdp_common.py`'s N-ERP-only functions, `search_tcode.py`,
`execute_filters.py`, `export_to_excel.py`, `run_nerp_workflow.py`, the
N-ERP tests, `SKILL.md`) is out of scope for this package and is never
imported from it.

## 1. Target package layout

```
src/gmes/
    __main__.py                 # python -m gmes
    cli/
        app.py                  # argparse wiring + dispatch, nothing else
        commands/                # login, find, describe, run, record, replay,
                                 # data, doctor, version, inspect, demo, workflow
        rendering.py             # ported from gmes_ui.py verbatim
        narrator.py              # ported from run_gmes_workflow.Narrator
        prompts.py               # ask/Questions/InputClosed/pause
        errors.py                # exit-code mapping
    application/                 # orchestration only (use-cases), no domain logic
        run_screen_uc.py  run_many_uc.py  sign_in_uc.py  connect_uc.py
        record_uc.py  replay_uc.py  find_screen_uc.py
        workflow_session.py      # the interactive RECORD/REPLAY session loop
        prodplan_recipe.py       # nightly Production Plan policy (poNo-drop, filename)
        doctor_uc.py
    browser/                     # forked cdp_common subset (shared primitives only)
        chrome.py  cdp.py  interaction.py  waits.py  screenshots.py
    auth/
        credentials.py           # DPAPI store, ported near-verbatim
        login_flow.py            # SSO race, direct_login, complete_sso
        session.py                # is_logged_in, wait_for_login_or_session, ensure_browser
    nexacro/
        app_state.py  dom.py  popups.py  js_snippets.py
    discovery/
        screen_discovery.py       # discover(), left_options, org_trees
        screen.py                  # the Screen class, trimmed
        catalogue.py                # gdsMenuList search/open (from gmes_open_screen.py)
        fingerprint.py              # fingerprint(), describe_change()
    screens/
        filters.py  grids.py  organization.py  input_events.py  verification.py
    query/
        form_locator.py  dataset_reader.py  dataset_writer.py   # paged reads live here
    export/
        excel.py  csv_export.py  naming.py
    profiles/
        refs.py  store.py  drift.py
    diagnostics/
        checks.py  report.py       # absorbs the 7 probe/inspect scripts + gmes_demo.py
    contracts/
        screen.py  login.py  run.py  profile.py  dataset.py
    paths.py                       # single source of truth for %LOCALAPPDATA%\GMES
    config.py  logging_setup.py  _version.py

tests/
    unit/            # ported offline tests (56+2 existing, plus new ones)
    fixtures/nexacro_snapshots/   # captured, token-scrubbed JSON for offline replay
    live/            # unchanged in spirit: real-Chrome, read-only, opt-in

packaging/
    gmes.spec  build.ps1
pyproject.toml
```

`application/` is orchestration only — the actual logic that made
`gmes_core.py` a god module is distributed to `screens/`, `discovery/`,
`query/`, `export/` by responsibility, not renamed into one new blob.

## 2. Old → new mapping (by target package)

- **browser/** ← `cdp_common.py`'s shared functions, corrected against the
  real call graph (Phase 3 grepped every `gmes_*.py` file's `cdp_common`
  usage rather than trusting a static read): `cdp.py` (`apply_proxy_bypass`,
  `CDP_HOST`, `CDP_PORT` [now read from `GMES_CDP_PORT`, not
  `NERP_CDP_PORT` - decouples a port setting that used to silently affect
  both automations], `next_id`, `ipv4`, `get_tabs`, `send`, `evaluate`,
  `connect`, `navigate_page`, `cdp_is_up`, **and `get_page_tab`**);
  `chrome.py` (`find_chrome`, `default_user_profile_dir`,
  `chrome_is_running`, `working_profile_dir`, `clone_user_profile`,
  `launch_chrome_with_user_profile`, `close_browser`,
  `LAST_CHROME_PROCESS`); `cdp.py` also gained `list_windows` in Phase 4
  (ported from `gmes_common.py` — pure CDP tab listing with no Nexacro
  involvement, so it lives here rather than in `nexacro/`);
  `interaction.py` (`click_element_by_rect`,
  `dispatch_key_combo`, plus `JS_IS_VISIBLE`/`JS_SET_VALUE` as a temporary
  home until `nexacro/js_snippets.py` exists in Phase 5a); `screenshots.py`
  (`capture_screenshot`, `screenshot_on_failure`).
  **`get_page_tab` was corrected from excluded to included**: it looked
  N-ERP-only (default `prefer_url_substring="nerps"`) but is directly
  imported by `gmes_common.py` and `gmes_connect.py`, and transitively
  needed by `navigate_page`/`capture_screenshot` - the plan's original
  static-read exclusion was wrong, fixed once the actual imports were
  checked.
  **No `waits.py`**: the only generic busy-wait in `cdp_common.py`
  (`wait_for_busy_indicator_clear`) polls an SAP-shell element id G-MES
  never uses; G-MES's own settle-detection is Nexacro-dataset-based and
  belongs in `screens/verification.py` (Phase 5), not a generic primitive
  here.
  **Also confirmed N-ERP-only and excluded** (grep found zero G-MES call
  sites, direct or transitive): `profile_dir`, `launch_chrome`,
  `connect_with_retry`, `find_visible_leaf_by_text`, `find_visible_by_title`,
  `describe_visible_dialog`, `wait_for_busy_indicator_clear`,
  `read_selection_screen_state`, `wait_for_selection_screen_ready`,
  `is_webgui_candidate`, `score_webgui_tab`, `get_webgui_tab`.
- **auth/** ← `gmes_credentials.py` (whole file, minus its CLI `main()` →
  `credentials.py`, resolving its store path through `gmes.paths.
  credentials_path()` instead of a module-local constant) +
  `gmes_login.py` split into `login_flow.py` (SSO/direct-login mechanics)
  and `session.py` (`ensure_browser`, `open_gmes`,
  `wait_for_login_or_session`, plus `is_logged_in` from `gmes_common.py`).
  `login_flow.py`/`session.py` have a real mutual dependency (session needs
  `login_error`/`BTN_SSO`, login_flow needs `is_logged_in`) broken with a
  local import inside `login_flow.wait_for_sso_window()`, the same pattern
  `browser/chrome.py`'s `close_browser()` already uses for its own
  `cdp.py`/`chrome.py` cycle. Phase 6a's `application/sign_in_uc.py` now
  consumes `LoginOutcome`/`LoginAttempt` for the non-CLI attempt and retry
  policy; `FAILED` retries, while `OK` and `REJECTED` return immediately.
- **nexacro/** ← `gmes_common.py`, ported across Phases 4 and 5b: `app_state.py`
  (`storage_state`, `prune_nexacro_cache`, `app_is_built`), `dom.py`
  (`js_find_by_id`, `click_by_id`, `set_value_by_id` from Phase 4's login
  needs, plus `js_find_elements`/`find_elements`/`click_control` added in
  5b — pattern-based lookup by id-regex/CSS-class/visible-text, needed by
  `screens/verification.py`'s `poll_inquiry()` to find the Inquiry button,
  which has no stable full id), `popups.py` (all three popup functions),
  `js_snippets.py` (re-exports `JS_IS_VISIBLE`/`JS_SET_VALUE` from
  `browser.interaction` — see the dependency-direction note below).
  `gmes_tab`/`connect_gmes` moved to `application/connect_uc.py`
  (orchestration, not a DOM primitive), also built early for the same
  reason; `is_logged_in` moved to `auth/session.py` per the plan.
  **Dependency direction correction (HISTORY.md 31.2)**: `JS_IS_VISIBLE`/
  `JS_SET_VALUE` stay defined in `browser/interaction.py`, not
  `nexacro/js_snippets.py` as Phase 3 anticipated — they are generic DOM
  predicates, not Nexacro-specific, and `nexacro/__init__.py` eagerly
  importing `dom.py` (which needs `browser.interaction`) means `browser/`
  importing back from `nexacro/` is a real circular import, caught live by
  `python -c "import gmes.auth"`. `nexacro/` depends on `browser/`, never
  the reverse.
- **screens/** ← DONE (Phase 5b). `normalise_date`/`fit_date_to_field`/
  `words`/`is_date_field`/`date_targets`/`match_filter` → `filters.py`;
  `choose_grid`/`digits_only` → `grids.py`; `tick_org`/`org_selection` →
  `organization.py`; `_key_events`/`type_text` → `input_events.py`;
  `read_rows`/`verify_rows`/`poll_inquiry` → `verification.py`. All now
  take `gmes.contracts` dataclasses (`ScreenInfo`/`FilterRef`/`GridRef`)
  instead of loose dicts. Tested by `tests/unit/test_filters.py` and
  `test_grids.py` (pure logic); `tick_org`/`org_selection`/`type_text`/
  `poll_inquiry` remain live-verified-only, same as in `gmes_core.py`
  (HISTORY.md Phase 14.9 — nothing here needs a browser to unit test
  except by mocking `evaluate()`, which isn't done for these).
- **discovery/** ← DONE (Phase 5c). `discover`/`left_options`/`org_trees`
  → `discovery/screen_discovery.py` — this is where a raw JS_DISCOVER/
  JS_LEFT_OPTIONS/JS_ORG_TREES dict is actually turned into `ScreenInfo`/
  `FilterRef`/`GridRef`/`OptionRef`/`TreeRef`/`QuickViewRef` for the first
  time in the migration; `discover()` raises `RuntimeError` (with the
  browser's own reason) instead of returning `{"found": false}`, since its
  only failure mode ("screen not built yet") is a normal, expected state
  during `open_screen()`'s polling loop, which now catches it the same way
  `auth/session.py`'s `wait_for_login_or_session()` already treats
  transient failures during a poll. The `Screen` class →
  `discovery/screen.py`, every method rewritten onto typed attribute
  access (`flt.column` not `flt["column"]`), calling into
  `screens/grids.py`'s `choose_grid` and `screens/organization.py`'s
  `tick_org`/`org_selection` rather than inlining that logic.
  `gmes_open_screen.py`'s catalogue search/open (library functions only,
  no CLI/argparse) → `discovery/catalogue.py`. `gmes_profile.py`'s
  `fingerprint`/`describe_change` → `discovery/fingerprint.py`; profile
  references and persistence are now in the Phase 5f `profiles/` package
  (`refs.py`, `store.py`, and `drift.py`). The profile/ref values remain
  plain dicts so their JSON storage shape stays explicit and stable.
  Phase 5e restored `Screen.export_excel()`/`to_csv()` as delegations to
  the export package, with offline tests of their typed export boundary.
- **query/** ← `form_locator.py`/`dataset_reader.py`/`dataset_writer.py`
  pulled forward into Phase 5b (`gmes_data.py`'s `JS_HELPERS`/
  `js_list_forms`/`js_find_column`/`list_forms`/`js_read`/`read_dataset`/
  `js_set_values`/`set_filter`), because `screens/verification.py` needs a
  working read path to be testable at all. **Phase 5d complete:**
  `read_dataset_paged()` yields `DatasetPage` values from bounded offset/limit
  CDP calls, advancing by the rows actually returned and stopping at the
  reported total or an empty page. `read_dataset(limit=-1)` drains those pages
  and preserves its legacy dictionary result; positive bounded reads retain
  one CDP call. `DatasetResult` is deliberately not wired yet because
  `screens/verification.py` still consumes dictionary access. Offline tests
  cover 850 ordered rows and the empty case; the required manual live
  comparison against a real 800–1500-row result remains open.
  - **Known bug, not yet fixed**: `gmes_data.py main()`'s `read` command reads
    the row limit from `argv[4]` instead of the documented `argv[3]` — a
    user-supplied limit is silently ignored (pinned by
    `tests/unit/test_gmes_data_argv_bug.py`; the fix lands with a proper
    `--limit` flag when `cli/commands/data.py` is built in Phase 6).
- **export/** ← `gmes_core.py`'s `download_excel`/`is_drm_protected`/
  `check_download` → `excel.py`; `gmes_data.py`'s `write_csv` →
  `csv_export.py`, which consumes `DatasetPage` values from
  `query.dataset_reader.read_dataset_paged()` one at a time rather than
  materialising the complete result. It keeps UTF-8 BOM, omits private
  (`_...`) columns, and drops only rows empty across all exported columns.
  `safe_name` plus `gmes_daily_prodplan.py`'s established Production Plan
  filename convention → `naming.py`. `Screen.export_excel()` and `to_csv()`
  are small delegations to these modules; `to_csv()` passes the discovered
  grid's form code and dataset rather than guessing either.
- **profiles/** ← DONE (Phase 5f). `gmes_profile.py`'s
  `field_ref`/`grid_ref`/`tree_ref` are now the explicit persistence
  allowlist in `refs.py`: it copies only stable names, never geometry,
  generated instance ids, dataset contents, session tokens or credentials.
  `store.py` provides `load`/`known`/`forget`/`save` at
  `paths.profiles_dir()` (`%LOCALAPPDATA%\GMES\profiles\`), rather than
  beside the executable. `drift.py` owns remembered-value recovery and
  non-empty merging and reuses `discovery.fingerprint` for the existing
  fail-safe drift comparison; it does not silently repair a profile.
- **application/** ← Phase 6a complete for `run_screen_uc.py` (`run_screen`
  and `print_summary`), `run_many_uc.py` (sequential, failure-isolated batch),
  and `sign_in_uc.py` (one auth attempt, typed retry policy and date parsing).
  `run_screen(ws, RunSpec(...))` returns `RunResult`, preserving verification,
  applied values, dates, files, profile use and timing. A changed profile is
  refused for replay and the newly discovered screen is used; saving occurs
  only after successful query, verification and requested file delivery.
  `prodplan_recipe.run_prodplan(ws, ...)` owns the nightly default date,
  known dataset, strict planYmd check, filename and paged poNo subtotal rule;
  it delegates screen running to the generic use case. Callers own sockets
  and browser lifecycle. Default exports keep `Data Hub Folder/GMES` under
  the caller's working directory, never under the installed package.
  No CLI parsing has been added. RECORD/REPLAY and workflow-session use cases
  remain later Phase 6 work; legacy callers remain untouched until Phase 11.
- **cli/** ← `gmes_ui.py` → `rendering.py` (verbatim, already
  presentation-only); `Narrator` class → `narrator.py`; `ask`/`Questions`/
  `InputClosed`/`pause` → `prompts.py`; new thin `commands/*.py` replace
  `gmes_report.py`, `gmes_open_screen.py`'s CLI, `gmes_data.py main`,
  `gmes_login.py main`, `gmes_credentials.py main`.
- **diagnostics/** ← new home for `gmes_connect.py`, `gmes_inspect.py`,
  `gmes_find.py`, `gmes_dump.py`, `gmes_probe_nexacro.py`,
  `gmes_probe_query.py`, `gmes_probe_excel.py`, `gmes_probe_search.py`,
  `gmes_probe_shell.py` — as named checks/subcommands, not 7 scripts.
- **contracts/** — new; formalizes today's ad hoc dicts (see below).
- **logging_setup.py** ← `gmes_log.py`, porting the `_Tee`/redaction
  discipline and fixing the known `isatty()` bug as part of the move.

## 3. Contracts

Plain `@dataclass` (no new dependency), replacing loose dicts that cross
module boundaries today:

- `screen.py`: `ScreenInfo`, `FilterRef`, `GridRef`, `TreeRef`, `OptionRef`
- `login.py`: `LoginOutcome` (enum: OK/FAILED/REJECTED), `LoginAttempt`
- `run.py`: `RunSpec`, `RunResult`, `ExportResult`
- `profile.py`: `ProfileRecord`, `ProfileDrift`
- `dataset.py`: `DatasetPage`, `DatasetResult`

## 4. Runtime state (`%LOCALAPPDATA%\GMES\`)

```
%LOCALAPPDATA%\GMES\
    credentials.dat        # moved from GMES_Automation\, one-time migration
    profiles\<CODE>.json   # was SCRIPT_DIR/screens
    logs\gmes_<date>.log
    screenshots\
    cache\nexacro\
    config\settings.json
```

The Chrome CDP profile copy stays at
`%LOCALAPPDATA%\Google\Chrome\CDP Profile` (unchanged) — already outside
"beside the executable" and not worth moving.
