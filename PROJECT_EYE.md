# Project Eye

**Current architecture (2026-09-13): the flat legacy engine is the
production core for both systems. There is no `src/gmes` package — it was
removed after its useful capabilities were classified and, where proven,
ported. See [CAPABILITY_RESCUE_MAP.md](CAPABILITY_RESCUE_MAP.md) for the
per-capability disposition and [HISTORY.md](HISTORY.md) Phase 57 for the
full restoration record. The donor code is not present as a directory in
this tree; it is recoverable from Git history at commit `59eb838` and from
branch `archive/standalone-gmes-before-removal`.**

```text
SYSTEM: Enterprise automation
  DOMAINS: N-ERP (active) | G-MES (active)
    SHARED INFRASTRUCTURE: cdp_common.py (CDP transport, Chrome launch,
        screenshots) - imported by both domains; a change to it must keep
        both suites green.
    N-ERP:
      ENTRANCES: search_tcode.py | execute_filters.py | export_to_excel.py
                 | run_nerp_workflow.py (orchestrator)
      RUNTIME: Chrome (throwaway profile via cdp_common.launch_chrome()),
               SAP GUI for HTML inside a Fiori shell
    G-MES:
      ENTRANCES: GMES_Workflow.bat (primary Windows entry)
        - no arguments  -> python run_gmes_workflow.py   (guided workflow)
        - with arguments -> python gmes_report.py run %*  (direct command)
      CODE: gmes_core.py (screen control) | gmes_login.py (sign-in,
            AD SSO + form fallback) | gmes_common.py (popups, connection) |
            gmes_open_screen.py (catalogue) | gmes_profile.py (record/replay
            fingerprints) | gmes_data.py (dataset read) | gmes_ui.py |
            gmes_log.py | gmes_report.py | gmes_credentials.py
      RUNTIME: Chrome CDP profile copy at
               %LOCALAPPDATA%\Google\Chrome\CDP Profile (via
               cdp_common.launch_chrome_with_user_profile()),
               credentials at %LOCALAPPDATA%\GMES_Automation\credentials.dat
```

Both `GMES_Workflow.bat` branches, and every G-MES entrance, reach the flat
legacy modules only. **Zero `gmes.*` package imports** - this is
mechanically enforced by `tests/test_legacy_entrance.py`, which imports each
entrance in a fresh interpreter and asserts no `gmes` or `gmes.*` module
ever loads, and separately checks the `.bat` text (case-insensitively) for
`PYTHONPATH`, `python -m gmes` or `gmes.bat`.

## Credential authorities

Two credential locations exist on a machine that has run both the legacy
and (formerly) the frozen engine. Both remain protected; **no migration or
consolidation between them is authorised**, and removing this repository's
`src/gmes` code does not authorise touching either real file:

| Location | Belongs to |
|---|---|
| `%LOCALAPPDATA%\GMES_Automation\credentials.dat` | The supported legacy runtime (`gmes_credentials.py`) — the one in active use |
| `%LOCALAPPDATA%\GMES\credentials.dat` | The now-removed frozen donor package — historical, not read by any code in this tree |

## Rules enforced mechanically

`tests/test_legacy_entrance.py` is the enforcement point for this
architecture (it replaced `tests/unit/test_architecture_rules.py`, which
enforced the now-removed package's own internal layering and had nothing
left to check once that package was gone). It proves, per entrance:

- the entrance loads flat legacy modules from the repository root and never
  a `gmes.*` package module;
- both `GMES_Workflow.bat` branches reach the correct legacy program;
- the launcher text cannot re-establish a path into a `src/gmes`-shaped
  package (`PYTHONPATH`, `python -m gmes`, `gmes.bat`, matched
  case-insensitively).

## History this file used to describe

Before 2026-09-13, this file (and `ARCHITECTURE.md`, `CURRENT_STATE.md`,
`README.md`, `GMES_SKILL.md`, `HOW_TO_USE.md`, `AGENTS.md`) described a
different, larger architecture: a `src/gmes` standalone Python package
(`cli/ → application/facade.py → domain capabilities`) intended to replace
this flat engine entirely. It reached real live G-MES sessions (HISTORY.md
Phases 1-56) and several genuine defects were found and fixed inside it.
The project owner then decided the flat legacy engine should remain the
core and the package should be removed (HISTORY.md Phase 57) - not because
the ideas in it were wrong, but because the architecture had grown larger
than the problem needed. `CAPABILITY_RESCUE_MAP.md` records what from that
package was ported, what was already covered by the legacy engine, what
was preserved only as design knowledge, and what was discarded, each with
its reason. This paragraph is the only place this document still describes
that architecture, and it is explicitly historical.
