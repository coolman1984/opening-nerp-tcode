# Operating rules for AI agents working on this project

**Read this file completely before your first tool call. Read
[HISTORY.md](HISTORY.md) before changing any automation logic.**

This project drives two live enterprise systems inside Samsung's corporate
network — N-ERP (SAP) and G-MES (Nexacro) — with real credentials, against
real production data, unattended, at night. Almost every failure this
project has suffered produced **no error at all**: a click that landed on
empty space, an export of the wrong day, a row count quietly 85 too high.
The rules below exist because of specific incidents, each recorded in
HISTORY.md.

---

## 1. The mandatory update rule

**Any change to behaviour requires a HISTORY.md entry in the same commit.**

Add an entry whenever you:

- fix a bug, however small
- discover how one of these systems actually behaves
- change a wait, a selector, a timeout, or an identifier
- find that something documented here is wrong

Use the existing shape — **Symptom / Cause / Fix / Lesson** — and describe
the *observed behaviour*, not your intention. "Waits longer now" is useless;
"Nexacro clears the dataset on Inquiry, so stable zeros are not a finished
query" is the whole point.

This rule exists because the original `SKILL.md` told callers to pipe data
into stdin months after the code had switched to command-line arguments. The
documentation was confidently wrong, and cost real debugging time.

If a discovery is a durable property of one of the systems (not a one-off
bug), also add it to the numbered gotchas in [SKILL.md](SKILL.md) (N-ERP) or
[GMES_SKILL.md](GMES_SKILL.md) (G-MES).

---

## 2. Safety rules — non-negotiable

### 2.1 Never delete or modify the user's real Chrome profile
`C:\Users\<user>\AppData\Local\Google\Chrome\User Data` holds their logins,
extensions and history.

- `launch_chrome()` **deletes** its profile directory. It is for the
  throwaway NERP profile only. **Never point it at the real profile.**
- `launch_chrome_with_user_profile()` copies and never deletes. Use this for
  anything touching the user's own session.

### 2.2 Never write credentials anywhere but the DPAPI store
No passwords in source, arguments, environment variables, log lines, commit
messages, or history entries. `gmes_credentials.py` is the only store.
Reading it out and printing it is a breach, not a debugging aid.

### 2.3 Never print or commit session tokens
Dataset dumps can contain live credentials. G-MES's integrated-search form
carries `tokenId` and `refreshTokenId` - full JWTs for the signed-in
session - in an ordinary-looking `dsAnyframeDVO`. Print only the columns you
need, and never paste raw dataset output into documentation, commits,
issues or chat.

### 2.4 Never commit exported data
`.gitignore` excludes `Data Hub Folder/`, `*.csv`, `*.png`. These files
contain production plans, order numbers and quantities. If you add a new
output location, add it to `.gitignore` in the same commit.

### 2.5 Ask before acting outside a read
These systems are live. Running an inquiry is read-only and fine. Anything
that **saves, submits, approves, deletes, or changes a value in the target
system** requires explicit user confirmation first, every time. Prior
approval for one action is not approval for the next.

### 2.6 Do not kill the user's browser without warning
`taskkill /F /IM chrome.exe` closes everything they have open. The NERP
orchestrator does this deliberately and says so. Nothing else should.

---

## 3. Engineering rules

These are distilled from the failures in HISTORY.md. Violating them
reintroduces bugs that have already been fixed once.

### 3.1 Never sleep a fixed duration — poll until observed
A tuned timeout is wrong in both directions: too short on a slow network (a
hard failure), needlessly slow on a fast one. A loop that exits the instant
it detects success makes a generous cap free.

```python
# Wrong
time.sleep(30)
button = find_button()

# Right
deadline = time.time() + 240          # generous cap, not an estimate
while time.time() < deadline:
    button = find_button()
    if button:
        break
    time.sleep(2)
```

### 3.2 Wait for the specific control you are about to use
Not `readyState`, not an element count, not "the target exists". Both
systems build their UI in JavaScript long after the document reports
complete. Waiting on a proxy signal produced a blank-page screenshot and a
"button not found" error while the page was still constructing itself.

### 3.3 Text matching must filter by visibility, length and area
`textContent` is inherited, so every ancestor of a button also "contains"
its label — and the outermost one comes first in document order. Clicking
its centre hits empty space and nothing happens, with no error. Use
`cdp_common.find_visible_leaf_by_text()` or the same discipline: visible,
inside the viewport, short text, smallest box wins.

A non-zero bounding box is **not** visibility. Some menus pre-render
off-screen (observed at `y = -99984`) before repositioning. `JS_IS_VISIBLE`
also requires the box to intersect the viewport.

### 3.4 Never hardcode a generated id
- **N-ERP**: dynpro ids like `M0:46:::2:34` are regenerated per screen. Match
  the input's `title` attribute, which is the field label.
- **G-MES**: work-screen ids embed a window number that changes on every open
  (`winPPM0219_0_516` → `_0_315`). Match the screen code from the breadcrumb
  (`P1112WM00`), the CSS class, or the visible label.

Only shell frames have fixed ids: `topFrame`, `loginFrame`, `mdiFrame`.

### 3.5 Verify the outcome of every step
Assume nothing succeeded because it did not raise. Confirm the screen
belongs to the t-code requested; confirm the result rows carry the date
asked for; confirm the file actually appeared. Two of the worst bugs here
were a run operating happily on the wrong screen and an export of the wrong
day.

### 3.6 Prefer the data layer to the screen
In G-MES, a grid only renders visible rows — reading the page silently
truncates large results. Read Nexacro Datasets (`gmes_data.py`). But
reconcile the counts: the dataset holds filler rows the grid hides.

### 3.7 Address the CDP endpoint by 127.0.0.1, never by name
On Windows `localhost` resolves to `::1` first and Chrome listens on IPv4
only, so every call waits for the IPv6 attempt to fail - 2.05s versus
0.013s, measured. That applies to the websocket URLs Chrome returns as
well; `cdp_common.ipv4()` rewrites them.

### 3.8 Save a screenshot on failure
`cdp_common.screenshot_on_failure()`. Take it on the **page** target; it
fails on an iframe target. An unattended job that fails at 02:00 leaves
nothing else to diagnose from.

### 3.9 Stop at the first thing you do not recognise
Do not fire the next shortcut into an already-open dialog, and do not guess
at further mechanisms. Report what is actually on screen. Continuing past an
unknown state destroys the diagnosis.

---

## 4. How to work on this project

### 4.1 Before changing automation logic
1. Read the relevant phase of HISTORY.md. The behaviour probably has a
   documented cause.
2. Check the gotchas in SKILL.md / GMES_SKILL.md.
3. Look at the live page with the inspection tools before writing a
   selector — never guess an id.

### 4.2 Inspection tools (read-only, safe)
```
python gmes_inspect.py              # what is on screen, every window
python gmes_find.py <text>          # search all frames by id/class/text
python gmes_dump.py "<js expr>"     # shape of any JavaScript object
python gmes_probe_nexacro.py        # the Nexacro form and dataset tree
python gmes_data.py forms           # open screens and their datasets
```

### 4.3 Testing
```
python tests/test_unit.py           # offline, N-ERP; must stay green
python tests/test_gmes_core.py      # offline, G-MES decision logic; must stay green
python tests/test_live_chrome.py    # real Chrome against the mock portal
```
The N-ERP mock (`tests/mock_nerp_server.py`) deliberately reproduces every
documented quirk. **When you fix a silent-failure bug, add a case to it.**
Two real bugs were caught by the mock and not by reading the code.

There is no mock for G-MES. Changes there are verified against the live
system with read-only operations and a screenshot.

### 4.4 Committing
- Explain **why**, with the observed symptom. The commit log is part of the
  record.
- Include the HISTORY.md entry in the same commit.
- Never commit data files or screenshots.

### 4.5 Do not
- Reintroduce a fixed sleep "because it usually works".
- Hardcode a path under `C:\Users\<someone>`.
- Add a dependency without a strong reason — this is stdlib plus
  `websocket-client`, and that is a feature in a locked-down corporate
  environment.
- Silently truncate a result. A cap that hides data is worse than no cap;
  one capped the form walk at 60 when the app had 206 and made the target
  screen appear not to exist.

---

## 5. Environment facts

| | |
|---|---|
| Platform | Windows 11, PowerShell |
| Python | 3.12 on PATH; only dependency is `websocket-client` |
| Chrome | 152 — **refuses remote debugging on the default profile** |
| Proxy | Corporate gateway intercepts localhost; `NO_PROXY` is set on import |
| N-ERP | `https://nerps.sec.samsung.net` — SAP GUI for HTML in a Fiori shell |
| G-MES | `http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html` — Nexacro |

Two separate network paths matter: the automation's calls to the CDP
endpoint (fixed by `NO_PROXY`) and Chrome's own page requests (which still
go through the corporate proxy). A local test server needs
`--no-proxy-server` on the browser; the real portals must not use it.

---

## 6. Where things are

```
cdp_common.py            Shared CDP layer: launch, connect, click, wait, screenshot
SKILL.md                 N-ERP skill + 28 numbered gotchas
GMES_SKILL.md            G-MES skill + 37 numbered gotchas
HISTORY.md               Every incident, cause and fix     <- keep updated
README.md                Project overview and setup

search_tcode.py          N-ERP step 1: open a T-code
execute_filters.py       N-ERP step 2: filters + Execute
export_to_excel.py       N-ERP step 3: export to .xlsx
run_nerp_workflow.py     N-ERP orchestrator

gmes_credentials.py      DPAPI credential store
gmes_login.py            G-MES unattended sign-in + notice popups
gmes_common.py           G-MES helpers: find, click, popups, signed-in state
gmes_data.py             Nexacro dataset read/write
gmes_core.py             THE CORE: one screen, driven completely   <- start here
gmes_open_screen.py      Open any of the 809 screens by code or name
gmes_daily_prodplan.py   The nightly Production Plan export (a caller of core)
gmes_demo.py             Guided read-only demonstration of every lesson
gmes_report.py           CLI over the core: describe / run / find any UI number
run_gmes_workflow.py     Interactive front end (GMES_Workflow.bat)
gmes_connect.py          First-contact / reconnaissance
gmes_inspect.py  gmes_find.py  gmes_dump.py  gmes_probe_*.py   Inspection tools

tests/                   Offline tests + live Chrome suite + mock N-ERP portal
Data Hub Folder/GMES/    Nightly output (git-ignored)
```
