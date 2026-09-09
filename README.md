# Enterprise system automation — N-ERP and G-MES

Browser automation for two Samsung enterprise systems, driven through the
Chrome DevTools Protocol.

| System | What it is | What is automated |
|---|---|---|
| **N-ERP** | SAP GUI for HTML inside a Fiori shell | Open a T-code, fill the selection screen, Execute, export the list to Excel |
| **G-MES** | Nexacro manufacturing execution system | Sign in unattended, run a report, export it — nightly, with nobody watching |

Both run on Windows against the live corporate network. The only third-party
dependency is `websocket-client`; everything else is the Python standard
library, which matters in a locked-down environment.

---

## Documentation

| File | Read it when |
|---|---|
| **[CLAUDE.md](CLAUDE.md)** | **Before touching anything.** Mandatory rules for humans and AI agents |
| **[HISTORY.md](HISTORY.md)** | Before changing automation logic — every incident, cause and fix |
| [SKILL.md](SKILL.md) | Working on N-ERP; 28 numbered gotchas |
| [GMES_SKILL.md](GMES_SKILL.md) | Working on G-MES; 31 numbered gotchas |

**The rule that keeps this project alive:** any behaviour change requires a
HISTORY.md entry in the same commit. Documentation that drifts out of date
is worse than none — this project has already lost debugging time to a
`SKILL.md` that confidently described an interface the code no longer had.

---

## Setup

```powershell
python -m pip install -r requirements.txt
```

Chrome is located automatically (Program Files, Program Files (x86),
`%LOCALAPPDATA%`, `PATH`, registry). Set `CHROME_PATH` to override.

For G-MES, store the login once — a dialog opens, nothing is echoed:

```powershell
python gmes_credentials.py set
```

It is encrypted with Windows DPAPI against your Windows account plus an
application salt: only that account, on that machine, can read it back.
Copying the file elsewhere yields nothing.

---

## N-ERP

```powershell
python run_nerp_workflow.py MB52 "Material Number=SM-A137FLBHMEB" "Plant=P703"
python run_nerp_workflow.py                 # interactive prompts
```

Or step by step:

```powershell
python search_tcode.py MB51
python execute_filters.py "Plant=P703"
python export_to_excel.py MB51
```

The export tries five different mechanisms in order — SAP binds export
shortcuts per transaction, so there is no universal one — and identifies the
resulting dialog by its content rather than assuming which flow it is in.

---

## G-MES

The nightly job — Production Plan by Order(Line), Division VD, yesterday:

```powershell
python gmes_daily_prodplan.py
```

Produces, in `Data Hub Folder/GMES/`:

- `Production Plan by Order(Line)_<date>_<time>.xlsx` — GMES's own export,
  identical to exporting by hand. **DRM-encrypted**: opens in Excel on a
  machine running the Samsung DRM client, unreadable by any library.
- `..._data.csv` — the same rows from the Nexacro data layer, readable by
  anything, with the 85 filler rows the grid hides removed.

Options: `--date YYYYMMDD`, `--days-back N`, `--division MOBILE`,
`--output-dir PATH`, `--no-csv`, `--keep-open`.

**Chrome must be closed** before the first launch of the day — Chrome will
not hand over a profile that is already in use, and since version 136 it
silently refuses to expose a debugging port on the default profile at all,
so the automation drives a copy of it.

### Guided demo

```powershell
python gmes_demo.py            # the full tour, read-only
python gmes_demo.py --quick    # skip the live query
```

Fourteen steps, each stating a lesson then proving it against the live
system, with screenshots. The fastest way to understand what G-MES does and
where it bites.

### Running any report

Give it a UI number and the filters; it discovers the rest from the screen.

```powershell
python gmes_report.py describe P1112UM00                 # what filters exist
python gmes_report.py run P1112UM00 --division VD --days-back 1
python gmes_report.py run P1112UM00 P1111UM00 --division VD --days-back 1
python gmes_report.py run P1112UM00 --set "Production Order=011074232146"
```

Screens run sequentially, one browser, each isolated — see the SEQUENCING
note at the top of `gmes_report.py` for why parallel would be a mistake.

### Reaching any screen

G-MES's ScreenID is the equivalent of an N-ERP T-code, and every screen
prints its own code in its breadcrumb. One entry point reaches all 809:

```powershell
python gmes_open_screen.py P1112UM00              # open by screen code
python gmes_open_screen.py "Work Calendar"        # open by menu name
python gmes_open_screen.py --find "production"    # search the directory
python gmes_open_screen.py --current              # what is open right now
```

`--find` prints the code, the menu id and the full breadcrumb for every
match, so a screen only has to be located once.

### Inspection tools (read-only)

```powershell
python gmes_inspect.py                 # everything on screen, every window
python gmes_find.py Inquiry            # search all frames by id, class or text
python gmes_data.py forms              # open screens and their datasets
python gmes_data.py read P1112WM00 dsMasterProdPlan 20
python gmes_probe_nexacro.py PPM       # the Nexacro form and dataset tree
python gmes_dump.py "nexacro.getApplication().mainframe"
```

Use these before writing a selector. Never guess an identifier — G-MES
renumbers work-screen ids on every open.

---

## Tests

```powershell
python tests/test_unit.py           # offline; must stay green
python tests/test_live_chrome.py    # real Chrome against a mock N-ERP portal
```

`tests/mock_nerp_server.py` is a deliberate trap course: a button that only
responds to real mouse events, a decoy iframe whose URL-encoded address
contains "webgui", a stale frame emitted before the live one, dialogs slower
than any fixed sleep, and a menu that pre-renders off-screen at `y = -99984`.
Two genuine bugs were caught by it and not by reading the code.

When you fix a silent-failure bug, add a case to the mock.

---

## Why this is written the way it is

Almost every failure here produced **no error at all** — a click landing on
empty space, an export of the wrong day, a row count quietly 85 too high, a
run operating happily on a screen from a previous test. The code therefore:

- polls until it observes the thing it needs, never sleeps a fixed duration
- waits for the specific control it is about to use, not a proxy for it
- matches on stable labels, classes and screen codes, never generated ids
- verifies the outcome of each step rather than assuming it worked
- saves a screenshot on failure, because an unattended job at 02:00 leaves
  nothing else to diagnose from

Each of those is a scar. They are documented in [HISTORY.md](HISTORY.md).
