# G-MES architecture

**Current, as of 2026-09-13 (HISTORY.md Phase 57).** The flat legacy engine
is the one G-MES implementation in this repository. See
[CLAUDE.md](CLAUDE.md) section 0 for the authority on this, and
[CAPABILITY_RESCUE_MAP.md](CAPABILITY_RESCUE_MAP.md) for what a briefly-tried
alternative architecture (`src/gmes`, 2026-09-12 to 2026-09-13) taught and
which of its ideas were ported, preserved, or ruled out with evidence.

N-ERP (`cdp_common.py`'s N-ERP-only functions, `search_tcode.py`,
`execute_filters.py`, `export_to_excel.py`, `run_nerp_workflow.py`, the
N-ERP tests, `SKILL.md`) is a separate system, sharing only `cdp_common.py`
with G-MES.

## Entrances

```text
GMES_Workflow.bat
  no arguments   -> python run_gmes_workflow.py       (guided interactive workflow)
  with arguments -> python gmes_report.py run %*      (direct command)
```

Both branches reach the same flat modules and never a package. This is
mechanically enforced, not just documented:
`tests/test_legacy_entrance.py` imports each entrance in a fresh
interpreter and asserts zero `gmes.*` package modules load, and checks the
`.bat` text (case-insensitively) for `PYTHONPATH`, `python -m gmes`, or
`gmes.bat` - the three ways an entrance drifted to a package engine before
(HISTORY.md Phase 56).

## Modules

```text
cdp_common.py            Shared CDP layer: launch, connect, click, wait, screenshot.
                          Imported by BOTH N-ERP and G-MES - a change here
                          must keep both offline suites green.

gmes_credentials.py       DPAPI credential store (%LOCALAPPDATA%\GMES_Automation\credentials.dat)
gmes_login.py             Unattended sign-in: AD SSO attempt, form-login fallback, notice popups
gmes_common.py            Shared G-MES helpers: tab/connection resolution, popups, signed-in state,
                          click/read primitives (js_find_by_id, click_by_id, is_logged_in)
gmes_data.py              Nexacro dataset read/write
gmes_profile.py           Record/replay: screen fingerprints, remembered field/grid/tree references
gmes_core.py              THE screen driver: open, filter, Inquiry, verify, export, profile-save
gmes_open_screen.py       Open any of the 809 screens by code or name (catalogue search)
gmes_report.py            CLI over gmes_core: describe / run / find any UI number
run_gmes_workflow.py      Guided interactive front end (the GMES_Workflow.bat no-arg path)
gmes_daily_prodplan.py    The nightly Production Plan export - a specialized caller of gmes_core,
                          with its own subtotal-row filtering and atomic CSV write
gmes_ui.py                Presentation only (ASCII-degrading terminal rendering)
gmes_log.py               Redacted, tee'd operation log

gmes_connect.py  gmes_inspect.py  gmes_find.py  gmes_dump.py  gmes_probe_*.py  gmes_demo.py
    Read-only reconnaissance/inspection tools (CLAUDE.md 4.2) - not part of the supported
    entrance chain above, and not covered by the same test gate.

gmes_sso_diagnose.py      Read-only AD SSO network-capture probe (HISTORY.md Phase 56/57.9) -
                          answers "what does the popup actually do" without ever touching
                          the password form. Independent tool, imports only gmes_common/
                          gmes_login/cdp_common.
```

## Runtime state

- **Credentials**: `%LOCALAPPDATA%\GMES_Automation\credentials.dat`, DPAPI-encrypted,
  written only by `gmes_credentials.py`.
- **Screen profiles** (record/replay): `screens\<CODE>.json`, next to the scripts (repo
  root, via `gmes_profile.py`'s `SCREENS_DIR`) - not under `%LOCALAPPDATA%`. Git-ignored:
  a filter value a profile remembers can be a production order number.
- **Logs/screenshots**: written next to the scripts by default
  (`cdp_common.screenshot_on_failure`/`gmes_log.py`) - not unified under one root; see
  CAPABILITY_RESCUE_MAP.md's "Runtime-path handling" entry for the (unbuilt) idea of doing so.
- **Browser profile**: `%LOCALAPPDATA%\Google\Chrome\CDP Profile`, a debuggable COPY of the
  user's real Chrome Default profile (CLAUDE.md 2.1a - never the real one, never deleted or
  refreshed automatically).

## Known, not-yet-fixed gaps

Tracked in [CAPABILITY_RESCUE_MAP.md](CAPABILITY_RESCUE_MAP.md)'s Final Decisions table with
evidence for each - notably: `gmes_credentials.py`'s `save()` writes directly rather than atomically
(temp file + rename); `gmes_data.py` reads a dataset in one unbounded call rather than paged.
None of these has a recorded live incident; none is fixed in HISTORY.md Phase 57.
