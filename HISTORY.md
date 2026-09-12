# Engineering history

Every problem this project has hit, what caused it, and what fixed it.

**This file is mandatory reading before changing anything, and mandatory to
update after changing anything.** See [CLAUDE.md](CLAUDE.md) for the rule.

The entries are not trivia. Nearly every one describes a failure that
produced *no error at all* — a click that landed on empty space, a report
exported for the wrong day, a row count that was quietly 85 too high. In
browser automation against enterprise systems, the dangerous failures are
the silent ones, and this file is the accumulated defence against them.

Each entry follows the same shape:

> **Symptom** — what was observed
> **Cause** — why it actually happened
> **Fix** — what was changed, and where
> **Lesson** — the general rule, if there is one

---

## Timeline at a glance

| Phase | Subject | Outcome |
|---|---|---|
| 0 | NERP skill, original build | Working, undocumented fragility |
| 1 | Audit | 4 defects found before running anything |
| 2 | NERP rebuild | Config centralised, 3 silent-failure bugs fixed |
| 3 | Test harness | Mock portal; caught 2 bugs the audit missed |
| 4 | GMES: getting connected | Chrome 136+ profile block |
| 5 | GMES: unattended login | DPAPI credentials, AD SSO, notice popups |
| 6 | GMES: the Nexacro data layer | Full data access, no screen scraping |
| 7 | GMES: nightly export | Delivered; DRM and filler-row discoveries |
| 8 | GMES: one way to reach any screen | 809-screen directory; open by code or name |
| 9 | GMES: guided demonstration | 14 steps, each proven live |
| 10 | GMES: generic report runner | Any UI number, filters discovered from the screen |
| 11 | GMES: interactive workflow + shell | Left-panel options; GMES_Workflow.bat |
| 12 | GMES: first real-user run | Stale filters, case, dates; subtotal rows explained |
| 13 | GMES: performance | 58.9s -> 2.1s startup; localhost cost 2s per CDP call |

---

# Phase 0 — the original NERP skill

Built before this history began. Automates SAP GUI for HTML (the "WebGUI")
inside the N-ERP Fiori portal over the Chrome DevTools Protocol.

Its `SKILL.md` already carried 25 numbered gotchas, all earned the hard way.
They are preserved in [SKILL.md](SKILL.md) and are not repeated here. The
most important, because they shaped everything later:

- The corporate proxy intercepts `localhost`, so CDP calls need `NO_PROXY`.
- `element.click()` does nothing on SAP controls; real mouse events required.
- The SAP screen lives in a separate cross-origin CDP target, not the page.
- Element ids are regenerated per screen; labels are stable.
- **Never sleep a fixed duration. Poll until the thing is actually there,
  with a generous cap.** This single rule recurs in almost every later fix.

---

# Phase 1 — audit

Read before running. Four problems found:

### 1.1 The project could not run at all
**Symptom** `websocket-client` missing from every Python on the machine.
**Cause** The `__pycache__` was built by Python 3.14; the Python on PATH was
3.12, without the package.
**Fix** Installed it; added `requirements.txt` and an import-time error in
`cdp_common.py` naming the exact install command.

### 1.2 Documented paths pointed at a different user
**Symptom** Every command in `SKILL.md` referenced
`C:\Users\a.selim\.claude\skills\...`.
**Cause** The doc was written on the original author's machine.
**Fix** Rewrote the commands to be run from the skill directory.
**Lesson** Absolute user paths in documentation are wrong the moment the
project moves.

### 1.3 Documentation contradicted the code
**Symptom** `SKILL.md` said the orchestrator "reads filters from interactive
stdin rather than argv" and told callers to pipe newline-separated input.
**Cause** `parse_cli_args()` had been added later; the doc was never updated.
**Fix** Rewrote that section. **This is the origin of the mandatory
history/doc update rule in [CLAUDE.md](CLAUDE.md).**

### 1.4 Redundant and duplicated logic
`wait_for_selection_screen_ready()` ran twice per orchestrated run;
`CDP_PORT` and the Chrome path were declared in two files; `chrome.exe` was
hardcoded to one install location.
**Fix** Single source of truth in `cdp_common.py`; `find_chrome()` searches
Program Files, Program Files (x86), `%LOCALAPPDATA%`, `PATH`, then the
registry, with `CHROME_PATH` as an override.

---

# Phase 2 — NERP rebuild

### 2.1 The Execute button was never actually pressed
**Symptom** On the mock portal: `Execute button: {'id': 'screen'}` — the
lookup returned the whole screen container. The click landed on empty space
and the run then waited forever for results that were never coming.
**Cause** `JS_LOCATE_EXECUTE` matched `/execute/i.test(el.textContent)` with
no visibility or length filter. `textContent` is inherited, so every
ancestor containing the button also matched, and the outermost one came
first in document order.
**Fix** Prefer the precise `(F8)` title; fall back to *short* visible text;
among survivors take the smallest bounding box. `execute_filters.py`.
**Lesson** This is gotcha #9 from the original skill, which the original
code documented and then violated three times over — the WebGUI toolbar
(found originally), the portal's "Go" button, and Execute. Text matching in
a nested UI must always filter by visibility, text length and area.

### 2.2 Export drove the wrong frame after Execute
**Symptom** `Connected to WebGUI: ...?stale=1` — the export step attached to
a stale placeholder frame while the real result list sat in another.
**Cause** `get_webgui_tab()` chose the candidate with the most text inputs.
Correct for a selection screen; **backwards after Execute**, when the live
screen is a result list with *zero* inputs and the stale placeholder still
has its one transaction-code box.
**Fix** Score on rendered content (element count + visible text + inputs).
A stale placeholder is a near-empty document in both states.
`cdp_common.score_webgui_tab()`.
**Lesson** A heuristic that identifies the right target in one state can
invert in another. Test it in every state the screen passes through.

### 2.3 Navigation aborted the whole run
**Symptom** `ConnectionResetError: [WinError 10054]` while sending
`Page.navigate`.
**Cause** A freshly launched Chrome shows `chrome://newtab`, a privileged
WebUI target. Navigating away is a cross-process swap and Chrome can tear
the DevTools session down before the reply is written. `Page.enable` on that
target has also been seen to hang outright.
**Fix** Launch Chrome with `about:blank` as its start page, and treat the
navigate acknowledgement as optional in `navigate_page()` — the navigation
has already been issued and the caller polls for the load anyway.

### 2.4 Diagnosis destroyed by continuing after an unknown dialog
**Symptom** The export error always blamed the last shortcut tried, never
the thing actually blocking progress.
**Cause** The mechanism loop kept firing shortcuts into an already-open
modal.
**Fix** Stop at the first unrecognised dialog and print that dialog's own
text. `export_to_excel.py`.

### 2.5 Smaller fixes
- Hand-picked CDP message ids (2, 10, 11, 30, 90, 95…) replaced with a
  shared counter; overlapping helpers could otherwise read each other's
  replies.
- `evaluate()` now always passes `returnByValue` and raises a named error on
  a JS exception. Several call sites had omitted it and worked only by
  accident, because primitives are inlined in the reply.
- `connect_with_retry()` retried only on `TimeoutError`; a page mid-navigation
  refuses the socket, which escaped as a crash. Now retries any connection
  failure.
- Failures save a diagnostic screenshot automatically (gotcha #8: it must be
  taken on the page target, never the iframe target).
- Gotcha #22 said "always sanity-check the page title matches" but nothing
  did. `verify_screen_matches()` now enforces it.

---

# Phase 3 — the test harness

The live portal needs corporate SSO, so `tests/mock_nerp_server.py` was
written as a deliberate reproduction of every documented quirk: a Go button
that only appears after a delay and only responds to real mouse events, an
AppDynamics decoy iframe whose URL-encoded address contains "webgui", a
stale near-blank frame emitted *before* the live one, dialogs that render
slower than a fixed sleep, and a dropdown that pre-renders at `y = -99984`.

`tests/test_live_chrome.py` drives it through real Chrome on its own CDP
port and profile, never touching the user's browser.

### 3.1 Making a loopback iframe a separate CDP target
**Problem** Same-origin iframes share the page's target, so the mock could
not reproduce the real portal's separate WebGUI target.
**Fix** Map two hostnames to loopback with `--host-resolver-rules` and force
out-of-process frames with `--site-per-process`.

### 3.2 The corporate proxy intercepts Chrome itself
**Symptom** The mock portal came back as a *Skyhigh Secure Web Gateway*
block page.
**Cause** `NO_PROXY` fixes Python's calls to the CDP endpoint. It does
nothing for Chrome's own page requests, which still go through the gateway.
**Fix** `--no-proxy-server` on the test browser only. The real portal is
allowed through the proxy, so production must not use this flag.
**Lesson** There are two separate network paths — the automation's calls and
the browser's — and they need separate treatment.

### 3.3 What the mock caught
Bugs 2.1 and 2.2 above were both found by the mock, not by reading the code.
Two of its assertions exist purely to pin behaviour that is otherwise
invisible: that a synthetic `.click()` is delivered and ignored while a
dispatched mouse event works, and that the live frame still wins after
Execute has cleared the input fields.

### 3.4 Test status
31 offline tests pass. The live suite reached 8 passes — every export flow —
before the tool session tore down its background browser, which surfaced as
9 `ConnectionRefused` errors. That is an infrastructure interruption, not a
code failure, but **the live suite has not yet completed a full clean run**
and that remains open.

---

# Phase 4 — GMES: getting connected

Target: `http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html`
Built with **Nexacro**, not SAP WebGUI. Requirement: use the real Chrome
profile, because the site needs its extensions and logins.

### 4.1 Chrome silently refuses to debug the default profile
**Symptom** Chrome launched, but port 9444 never opened. No error anywhere.
**Cause** **Chrome 136 and later ignore `--remote-debugging-port` whenever
`--user-data-dir` is the default profile directory.** A deliberate security
fix — it stopped malware reading cookies out of a live browser through
DevTools. The flag is not rejected loudly; it is silently dropped. Observed
on Chrome 152.
**Fix** `clone_user_profile()` copies the profile to
`%LOCALAPPDATA%\Google\Chrome\CDP Profile` with robocopy, excluding caches
(928 MB → 338 MB), and Chrome is launched against the copy. Extensions and
logins survive; session-only cookies do not, so the site may ask to sign in
once inside the copy.
**Safety** `launch_chrome_with_user_profile()` never deletes anything. The
NERP path deletes its throwaway profile; that code must never be pointed at
a real profile.

### 4.2 Getting the first look
`gmes_connect.py` reported: Nexacro app, **real DOM elements, no canvas**,
and clean stable ids like
`mainframe.vFrameSet1.loginFrame.form.divLogin.form.btnLogin`.
**Consequence** The best case. Everything from the NERP work applies, and
more reliably, because controls have meaningful names.

---

# Phase 5 — GMES: unattended login

### 5.1 AD SSO is not automatic
**Symptom** Clicking "AD SSO Login" opened a Samsung ADFS window that asked
for a Knox ID and password.
**Fix** Credentials are stored with Windows DPAPI (`gmes_credentials.py`),
encrypted against the Windows account plus an application salt. Only that
user, on that machine, can decrypt; copying the file elsewhere yields
nothing. Same mechanism Chrome uses for its own saved passwords.

### 5.2 No keyboard attached to the prompt
**Symptom** `EOFError: EOF when reading a line` at the credential prompt.
**Cause** Launched from a runner with no interactive stdin.
**Fix** Fall back to a small Tk dialog when `stdin.isatty()` is false.
**Lesson** An unattended tool cannot rely on `input()` existing.

### 5.3 The readiness check was too weak
**Symptom** "the 'AD SSO Login' button was not on screen"; the diagnostic
screenshot was a blank white page.
**Cause** Readiness was "more than 200 elements exist". Nexacro builds its
UI in JavaScript long after `readyState === "complete"`, and the count
crossed the threshold while the page was still blank.
**Fix** `wait_for_login_or_session()` waits for a **named control** — either
the AD SSO button or the signed-in user name.
**Lesson** Wait for the specific thing you are about to use, never a proxy
for it.

### 5.4 The notice popup was checked too early
**Symptom** "Popups closed: none appeared", then a `--status` check moments
later reported one open.
**Cause** GMES opens the Notice window a few seconds *after* the user name
appears in the top bar. A single check races it.
**Fix** `close_popups_when_they_appear()` waits for the first popup, closes
it, and keeps watching until several consecutive checks are clear — which
also catches notices that queue up. A real run closed two in succession.

### 5.5 Closing popups by type, not by name
The Notice window's element id contains Korean text
(`...portalFrame.공지사항.titlebar.closebutton`). Matching that name would
close exactly one popup on one screen forever.
**Fix** Match the CSS class Nexacro assigns to floating child windows
(`.TitleBarControl.titlebarChildFrame` → `.closebutton`), scoped to child
frames only so the user's work screen is never closed.
**Caveat, unresolved** The Excel export dialog is also a child frame. The
popup closer must therefore run **only during login**, never around an
export. See Open items.

### 5.6 Detecting "signed in"
The obvious test — the login button is gone — never becomes true, because
Nexacro keeps the login frame in the DOM and merely hides it. Test for the
presence of the user-name button in the top bar instead.

---

# Phase 6 — the Nexacro data layer

The decisive discovery of the project.

### 6.1 A Nexacro grid only renders the rows you can see
Scraping the page would silently truncate a large result — a 5,000-row
report becoming the 20 rows on screen, with the job reporting success. The
real rows live in Nexacro **Datasets**, in JavaScript.

### 6.2 Two traps that make the app look empty
1. Child frames live in `_frames`, a Nexacro `ObjectArray` with numeric
   indexing. There is no `frames` property; walking it finds nothing.
2. **A work screen is not a frame.** It is loaded into nested `Div`
   components, each carrying its own `.form`. Stopping at frames finds only
   an empty `WorkMain` shell.

### 6.3 A cap that hid the answer
**Symptom** The work screen was missing from the form listing.
**Cause** The walker capped at 60 forms; the app has 206.
**Lesson** A safety cap that silently truncates results is worse than no cap.

### 6.4 Window ids are renumbered on every open
The same Inquiry button was `winPPM0219_0_516` on one visit and
`winPPM0219_0_315` an hour later. **Nothing inside a work screen may be
addressed by full id.** Match on the screen code from the breadcrumb
(`P1112WM00`), the CSS class, or the visible label. Only the shell frames
(`topFrame`, `loginFrame`, `mdiFrame`) have genuinely fixed ids.

### 6.5 The breadcrumb is the address
`PPM > Production Plan > … > Production Plan by Order(Line) [ P1112UM00 >
P1112WM00 ]`. Those codes are stable and are what the code targets.
The top search box also accepts a ScreenID, which is the intended way to
reach a screen without walking menus.

**Map of the Production Plan screen**

| Screen code | Role | Key datasets |
|---|---|---|
| `P1112WF00` | left filter panel | `dsFilterDVO` (dates) |
| `P1112WM00` | results | `dsMasterProdPlan` |
| `OrgCategory_GDS` | Org tab tree | `dsCatCommonTreeNodeDVO` |

---

# Phase 7 — the nightly export

### 7.1 The missing Division
**Symptom** Every query returned nothing; the screen said "Select Search
Criteria".
**Cause** No Division selected in the Org tree. *Reported by the user.*
**Fix** `select_division()` ticks the row whose `commonName` matches (VD is
`^V^C712A^T001`) by setting `_checked` on the dataset — the UI checkbox
follows. Found by name, not row number, because the tree is built from the
user's permissions.

### 7.2 Setting the date without touching the calendar
Writing `paramFromDate`/`paramEndDate` into `P1112WF00.dsFilterDVO` updates
the visible date box, because Nexacro binds the two. No date-picker
interaction needed.

### 7.3 "0 rows" while 790 were on their way
**Symptom** The job refused to export, reporting 0 rows; a screenshot taken
at the same moment showed 790 rows on screen.
**Cause** Nexacro **clears** the result dataset the instant Inquiry is
pressed and only refills it when the server answers. The settle-detector saw
a few stable readings of zero and called that "finished".
**Fix** Settle only on a count **above zero** that has stopped moving; give
an all-zero run a long grace period before concluding there is no data.
**Lesson** "Stopped changing" is not "finished" when the starting state and
the empty state look identical.

### 7.4 The Excel icon opens a dialog
It does not download. It opens `PopupExcelExport` — "Save to Excel", grid
already ticked, "save a single file" ticked — and the file arrives only
after **OK**.

### 7.5 The download went to the wrong folder
**Symptom** OK clicked, dialog closed, no file in the target folder.
**Cause** `Browser.setDownloadBehavior` was set on a CDP connection that was
then closed. The redirect died with it and the file went to Downloads.
**Fix** Set the download path on the *same* open connection that does the
clicking; watch the Downloads folder as a fallback.

### 7.6 The exported workbook is DRM-encrypted
**Symptom** `zipfile.BadZipFile: File is not a zip file`.
**Cause** The file begins `<## NASCA DRM FILE - VER1.00 ##>` — Samsung's
document rights management. It opens normally in Excel on a machine running
the DRM client, but **no library can parse it**.
**Consequence** Since the destination is a "Data Hub", the job also writes a
plain CSV straight from the dataset. Suppress with `--no-csv`.

### 7.7 85 phantom rows — the 701-vs-784 gap
**Symptom** The grid header said `Total 701` while the dataset held 784.
Later, `Total 790` against 875.
**Cause** The dataset carries **85 filler rows with no PO and no master
line** which the grid hides. 875 − 85 = 790, matching the screen exactly.
**Fix** The CSV drops rows with an empty `poNo`, so its count always agrees
with the screen. The GMES Excel export is unaffected — it exports the grid.
**Lesson** A row count from the data layer is not the same as the row count
a user sees. Reconcile them before trusting either.

### 7.8 Verified result
```
Plan date 20260908   Division VD
Signed in as 'Mohamed Fawzy'
Inquiry -> 790 rows
Excel : Production Plan by Order(Line)_20260909_133958.xlsx   86.2 KB  [DRM]
CSV   : ..._data.csv   790 rows (85 filler rows dropped)
```

---

# Phase 8 — one way to reach any screen

The user's observation: G-MES's top search box accepts a **ScreenID**, and
every screen prints its own code in its breadcrumb —
`... Production Plan by Order(Line) [ P1112UM00 > P1112WM00 ]`. That is the
same shape as N-ERP's T-code, so it should have the same one-line entry
point. Menus are four levels deep and translated; a code is short and
stable.

### 8.1 The catalogue is client-side — and there are two of them
`gdsMenuList` (1177 rows) holds every reachable screen: `menuId` (PPM0219),
`sysScreenId` (P1112UM00), English and Korean names, and `screenSn`, the
ancestor chain that reproduces the breadcrumb exactly. 809 rows are actual
screens. `menuId` is the real identity — it is what `gdsOpenMenu` records
and what the window is named after (`winPPM0219_0_603`).

**Wrong turn worth recording:** `gdsMenuList_` looked like the same
catalogue and was tried first. Its titles are Korean only (생산계획) and its
menuIds are a different series (`PM0001` vs `PPM0219`), so an English search
returned nothing and a join on menuId matched nothing. Two failed searches
before the real table was found.

### 8.2 Setting the search box value searches nothing
**Symptom** The box showed the query; the suggestion list stayed empty.
**Cause** The list is produced by the control's `onkeyup` handler.
Nexacro's `set_value()` assigns without any key event.
**Fix** Click the box to focus, then send per-character keyDown/char/keyUp.

### 8.3 The Notice popup is modal and swallows clicks
**Symptom** Clicking the search button did nothing at all — no error, no
dropdown.
**Cause** The Notice window is modal; the application behind it is greyed
out and every click is discarded.
**Lesson** Clear popups before interacting with anything, not just at login.

### 8.4 Clicking the obvious match opens nothing
**Symptom** The suggestion was found and clicked; no screen opened.
**Cause** The click hit `integratedSearch.form.divDetail.form.staTitle` —
the popup's detail panel, which displays the same text as the result row
and is the natural text match.
**Fix** Read `dsSearchResult` to choose the row by data, then click
`grdResult.body.gridrow_<n>.cell_<n>_0`.
**Lesson** When a popup shows the same text twice, matching on text picks
the wrong one. Choose by data, click by position.

### 8.5 Open is not active — the worst bug of this phase
**Symptom** The nightly job reported 0 rows. The date and division had been
set correctly and the screen was open.
**Cause** Three screens were open as tabs and **Work Calendar was in
front**. A background screen still accepts dataset writes, so the filters
applied to the right screen while the Inquiry click landed on the visible
one — a different report entirely, with no rows.
**Fix** `activate_screen()` clicks the screen's tab
(`mdiFrame.form.divTab.form.TAB_<winId>`) and confirms the window became
visible. The nightly job now activates before acting.
**Lesson** "The thing exists" and "the thing is in front" are different
questions, and only the second one governs where a click goes. This is the
same family as the stale-WebGUI-frame bug in Phase 2.

### 8.6 Result
```
python gmes_open_screen.py --find "production plan"   -> 809 screens, English + breadcrumb
python gmes_open_screen.py P1111UM00                  -> opened Production Plan by Model
python gmes_open_screen.py "Work Calendar"            -> opened M4151UM00
python gmes_daily_prodplan.py                         -> 790 rows, correct tab, both files
```

### 8.6a Waiting for an SSO window that was never going to open
**Symptom** `ERROR: the Samsung SSO window never opened` — but a `--status`
check moments later reported the user signed in as normal.
**Cause** Clicking AD SSO does not always produce an SSO page. When a
session cookie has survived in the profile copy, G-MES signs straight back
in. The wait only watched for the ADFS window, so a successful sign-in
looked like a failure.
**Fix** `wait_for_sso_window()` now takes the GMES connection and races the
window against `is_logged_in()`, returning `"already-signed-in"` when the
session restores itself. `gmes_login.py`.
**Lesson** When there are two ways for a step to succeed, wait for both. A
wait that watches only the path you expected turns the other path into a
failure.

### 8.6b A closed browser reported as a stack trace
**Symptom** Every tool failed with ~30 lines of urllib traceback ending in
`ConnectionRefusedError: [WinError 10061]`.
**Cause** The most common condition of all — the browser is not running,
often because a previous job closed it — surfaced as a raw exception about a
refused TCP connection to a port number.
**Fix** `gmes_tab()` catches it and raises one sentence naming the fix:
*"Cannot reach the automation browser... Start it with: python
gmes_login.py"*. `gmes_common.py`.
**Lesson** The most likely failure deserves the clearest message.

### 8.6c Process note — this rule was broken here
Both fixes above were shipped in the "one entry point" commit with only a
line in the commit message and **no HISTORY entry**, which is precisely what
the mandatory rule in [CLAUDE.md](CLAUDE.md) forbids. They are recorded here
retrospectively. The rule failed the first time it was tested; noting that
is more useful than quietly backfilling.

### 8.7 Security note
Dumping the integrated-search form's datasets printed `dsAnyframeDVO`,
which carries `tokenId` and `refreshTokenId` — **full JWTs for the live
session**. Raw dataset output must never be pasted into documentation,
commits, issues or chat. Print only the columns needed.

---

---

# Phase 9 — the demonstration

`gmes_demo.py` walks fourteen steps, each stating a lesson and then proving
it against the live system with a screenshot. It exists because the lessons
in this file are abstract until they are watched happening, and because a
demo that runs is a regression test for the whole stack: if any of the
fourteen breaks, something regressed.

Read-only throughout — it opens screens, searches and reads, and saves
nothing in G-MES.

### 9.1 The run confirmed the changing-id rule by accident
The results window was `winPPM0219_0_939` during the demo, having been
`winPPM0219_0_603` about an hour earlier and `_0_516` / `_0_315` on the day
before. Same screen, four different ids. Nothing in the code depends on
them; that is the entire point of gotcha #7.

### 9.2 Verified in one pass
```
809 screens in the directory
opened P1111UM00 by code, "Work Calendar" by name
3 tabs open -> activated winPPM0219_0_939 before acting
filter 20260909 -> 20260908 written through the dataset
Division VD ticked at ^V^C712A^T001
Inquiry -> 875 rows in 10.7s, measured
875 - 85 filler = 790, matching the grid exactly
```

### 9.3 A weakness in the demo itself, not the system
Step 2 ("the Notice popup") reports **0 popups**, because sign-in in step 1
has already closed them seconds earlier. The evidence is real but appears in
step 1's output rather than in the step that claims it. The demo shows the
capability without demonstrating the trap. Left as-is rather than
artificially reopening a popup, but worth knowing when reading the output.

---

# Phase 10 — a generic report runner

The request: give it a UI number and the filters, and let it work the screen
out for itself — no per-screen teaching, several screens per run.

### 10.1 Screens describe their own filters
Every Nexacro form carries `form.binds`, a table linking each control to the
dataset column behind it:
`divBasic.form.divCal.form.mskDateFrom → dsFilterDVO.paramFromDate`.
Read it, pair each control with the label rendered beside it, and a screen
lists its own filters. The result grid comes from the same place, via
`binddataset`. Verified across three unrelated screens (PPM ×2, MQM ×1).

### 10.2 Three things the binding table gets wrong on its own
- **Bound Statics are outputs, not filters.** `staPlanQty`, `staProgRate`,
  `staDelayLine` are computed displays. Offering them as filters would
  invite setting a value that means nothing. Classified by control-name
  prefix instead.
- **The shell contributes binds of its own.** `chkPersonal`, `chkLocal`,
  `userIdLike` come from the My Menu panel, not the report.
- **Labels came back as "6" and "8".** The nearest Static to a date box is a
  calendar day cell. Purely numeric and weekday Statics are now rejected as
  labels, which yields "Period" correctly.

### 10.3 Not every screen binds its filters
`Q2241UM00` (Process Defect Status) binds none — it sets them in code. A
bind-only tool reports "no filters" and looks broken. It now also lists the
visible-but-unbound inputs and says plainly that they cannot be set through
a dataset.

### 10.4 The worst bug of this phase — a lying row count
**Symptom** Running two screens in one command, both reported **875 rows**.
**Cause** The generic runner reused the nightly job's inquiry helper, which
polls `dsMasterProdPlan` on `P1112WM00` **by name**. For the second screen
that dataset still held the *first* screen's results, so the count — and the
settle-wait — watched the wrong report entirely.
**Evidence** The CSV, which used the discovered dataset, held **17** rows.
The file was right and the log was wrong.
**Fix** `run_inquiry_on()` polls the dataset discovered on the screen being
run, and additionally requires the count to be seen **changing**, so a
dataset left populated by an earlier run cannot be mistaken for a finished
query.
**Lesson** A wrong number beside a right file is worse than an outright
failure: nothing looks broken, so nobody checks. Anything reused across
screens must be parameterised by what was discovered, never by a name that
happened to be true once.

### 10.5 Sequential, not parallel — and why
Multiple UI numbers run one after another in a single browser, deliberately:
- Only one tab is in front, and a background screen still accepts filter
  writes — that is exactly the 8.5 bug, and parallel tabs reintroduce it by
  design.
- The Excel button and its "Save to Excel" dialog are global to the
  application; two exports would collide.
- Modal popups block the whole application, not one screen.
- Real parallelism needs a separate Chrome, profile copy (~340 MB) and SSO
  sign-in each — more authentication load and more ways to fail unattended.
- The measured cost is small: 11.8s and 28.3s of server time for two
  reports. G-MES answering is the bottleneck, not this tool.

Each screen is isolated, so one failure does not stop the rest, and the run
ends with a summary of what succeeded.

### 10.6 Verified
```
run P1112UM00 P1111UM00 --division VD --date 20260908
  P1112UM00  Production Plan by Order(Line)  875 rows  xlsx + csv
  P1111UM00  Production Plan by Model         17 rows  xlsx + csv
  2/2 succeeded
```
Both counts confirmed against the row counts in the delivered CSV files.

---

# Phase 11 — the interactive workflow, and the rest of the shell

The request: a G-MES equivalent of `NERP_Workflow.bat`, plus a warning that
the top module bar and the left sidebar had not been explored properly. Both
were right.

### 11.1 The left panel holds filter dimensions that are not "filters"
Bind-discovery (Phase 10) finds named fields. It finds **none** of these,
and every one changes what a query returns:

| Option | Effect |
|---|---|
| `Org` / `Prod` / `Fac` / `Proc` | which category tree the selection comes from |
| `STD` / `PLANT` | the organisation attribute |
| `Including Past Org.` | include closed organisations |
| `Plan Date` / `Create Date` | **which date the period means** |
| `General` / `Compare` / `OI` | the search mode |
| Quick View entries | Master vs Detail Prod. Plan — a different result set |

Running "yesterday" against **Create Date** instead of **Plan Date** returns
a plausible, completely different answer. Nothing would look wrong.

**Fix** Nexacro encodes the state in the CSS class — `_Sel`,
`Category_Sel`, `ToggleSearchV2` mean chosen; `_Dis`, `_Default` mean not.
`left_options()` lists all of them with their state; `set_option()` clicks
by label and **re-reads the class to confirm**. 16 found on the Production
Plan screen, including a Korean one (`실적일`) with no English twin.
**Order matters**: options are applied before the Division and the filters,
because switching a category tab or Quick View rebuilds the panel and
discards whatever was set.

### 11.2 The top module bar
`topMenuFrame.form.btn*` — `btnMyMenu`, `btnMCLabel`, `btnMCOI`,
`btnConfig`, `btnQuickLink`, plus `divTopSub` holding the module buttons
(MDE, PPM, MQM, FFM, ALM, AQM, MRM, WP). Mapped, but deliberately **not**
automated: the search box already reaches all 809 screens by code, so
walking the module bar would be a second, weaker path to the same place.
Recorded so the next agent does not have to rediscover it.

### 11.3 A generic CSV must not guess which column is the key
Filtering one Production Order returned **4** dataset rows for a single
visible line — three continuation rows the grid merges. The Production Plan
job drops rows with no `poNo`; a generic tool has no equivalent key on an
unknown screen. It now drops only completely empty rows and reports both
counts, rather than silently discarding rows whose meaning it cannot know.

### 11.4 Session expiry is real
Between one test and the next the session had expired, and clicking AD SSO
produced no SSO window within 45s — the run failed on the login page with
"Auth bad credentials" showing. A second attempt signed in normally. Worth
knowing before trusting a long unattended sequence: the sign-in step should
be retried once before the run is called a failure.

### 11.5 Verified
```
run_gmes_workflow.py
  UI number(s)          : P1112UM00
  (screen opened, its 8 filters listed, 16 left-panel options listed)
  Filter                : Production Order=011074232146   -> validated on entry
  Option                : Plan Date -> selected
  Division VD, date 20260908
  inquiry               : 4 rows in 8.2s   (875 without the PO filter)
  csv                   : 4 rows written
  1/1 succeeded
```

---

# Phase 12 — what a real user hit in five minutes

The first hands-on run of the interactive workflow found four defects that
none of the scripted tests had, because the tests only ever fed input the
way the author would type it.

### 12.1 A stale filter, inherited in silence — the serious one
**Symptom** A run asking for date 2026-09-07, Division VD, returned **0
rows**. The date was right. The division was right. Nothing looked wrong.
**Cause** G-MES keeps a screen alive behind its tab, and a filter typed into
it **stays there**. A Production Order entered during a *previous* run was
still in the box, so the query was "that PO on a day it did not run".
**Fix** `clear_stale_filters()` blanks the free-text (`edt`) fields the
caller did not name, before applying this run's own, and prints what it
cleared: `cleared : leftover Production Order=011074232146`. Combos and
checkboxes are deliberately left alone — they hold meaningful defaults
(`paramTecoYn` = "All", a status list = "1^2^3^4") and blanking those would
break the query a different way.
**Lesson** State that survives between runs is as dangerous as state read
from the wrong screen. Both produce a confident, wrong, empty answer.

### 12.2 Case-sensitive matching, with the answer in its own error
**Symptom** `Division 'vd' was not in the Org tree. Divisions present:
['SEEG-P', 'VD', ...]` — the error printed the value it had just refused.
**Cause** The org-tree comparison was exact.
**Fix** Case-insensitive comparison; screen codes uppercased for display, so
a run reported as `p1112um00` no longer reads like a different thing.

### 12.3 A date format that was accepted and then meant nothing
**Symptom** `2026-09-07` was taken without complaint.
**Cause** It was written verbatim into a filter that stores `YYYYMMDD`.
**Fix** `normalise_date()` accepts `20260907`, `2026-09-07`, `2026/09/07`,
**rejects** anything that is not a real calendar date, and the interactive
prompt validates while the user is still at the keyboard.

### 12.4 A misleading rejection
Typing `category=vd` as a filter was refused with only "no filter matches" —
true, but unhelpful, because Division is a different mechanism entirely.
Both the CLI and the prompt now say so and point at the Division question
and the `--option` controls.

### 12.5 An open item closed: the "filler" rows are SUBTOTALS
The user's screenshot showed the grid rendering **LINE SUM** and **PROC
SUM** rows. Checking the data confirmed it: those rows carry the same
`planQty` / `acrsQty` as the data row above and nothing else — no PO, no
line, no model — because the grid supplies those labels at render time and
the dataset stores only the aggregates. 875 − 85 = 790 is therefore fully
explained, and dropping rows with an empty `poNo` drops subtotals, not data.
Recorded in GMES_SKILL #28, which previously admitted it was an unexplained
inference.

### 12.6 Also
The wait before concluding "no rows" was 120s; a genuinely empty result now
takes 60s to report instead of two minutes.

---

# Phase 13 — "why does it do that when I am already logged in?"

The user asked why an already-signed-in session still printed *"Watching for
notice popups... Popups closed: none appeared"*. It was a fair question with
an expensive answer.

### 13.1 A 45-second vigil for a popup that could not arrive
**Symptom** `gmes_login.py` on an already-signed-in session took **58.9
seconds** and closed nothing. Every tool calls it first, so every command
paid it before doing any work.
**Cause** The Notice popup arrives a few seconds *after* sign-in (gotcha
#4), so the watcher polls for up to 45s. That watch ran unconditionally —
including on sessions that were signed in long ago, where any popup would
already be on screen and nothing new was coming.
**Fix** Wait only after an actual sign-in; otherwise sweep once and move on.
58.9s → 13.8s.
**Lesson** A wait that is correct in one state can be pure cost in another.
The condition that made it necessary has to be checked, not assumed.

### 13.2 `localhost` cost 2 seconds per CDP call
Profiling what remained gave the real surprise:

```
cdp_is_up()          2.05s        get_tabs via "localhost"
gmes_tab()           2.06s        another /json/list
connect_gmes()       4.14s        lookup + websocket connect
capture_screenshot() 4.25s        lookup + connect + PNG
TOTAL               12.50s
```

**Cause** On Windows `localhost` resolves to `::1` first, and Chrome's
DevTools endpoint listens on IPv4 only — so every call waits for the IPv6
attempt to fail before retrying. Measured directly:

```
localhost   3 calls: 6.14s      (2.05s each)
127.0.0.1   3 calls: 0.04s      (0.013s each)
```

A **150x** difference, paid by every target lookup. And by every websocket
too, because Chrome returns `webSocketDebuggerUrl` values pointing at
`localhost`.
**Fix** `CDP_HOST = "127.0.0.1"` for the HTTP endpoint, and `ipv4()` to
rewrite the websocket URLs Chrome hands back.

```
                       before    after
startup profile        12.50s    0.41s
gmes_login.py          58.9s     2.1s
full report run        ~75s      13.4s   (10.1s of which is GMES querying)
```

**Lesson** This was invisible because nothing failed — it was just slow, and
"enterprise systems are slow" is an easy thing to accept. Two seconds per
call was our own name resolution, not the corporate network.

### 13.3 A defect this introduced, caught immediately
Renumbering an earlier edit left `empty_grace` referenced in
`run_inquiry_on()` without being a parameter of it, so the first real run
after the change failed with `name 'empty_grace' is not defined`. Added to
the signature. Worth recording because it came from a bulk text replacement
that matched in a function it was not aimed at — the same class of mistake
as the hardcoded dataset name in Phase 10.4.

---

# Phase 14 — the core: any UI number, not just report-shaped ones

The request: *"a full working core tool to control any UI number of the
G-MES"*. `gmes_report.py` already ran a screen it had never been taught, so
the work was to find where "any" was not true. Eight places, below.

Everything moved into **`gmes_core.py`**; `gmes_report.py`,
`run_gmes_workflow.py` and `gmes_daily_prodplan.py` are now callers of it.
Read-only by decision: the core opens, filters, queries, verifies and
exports, and has no code path that saves or submits (CLAUDE.md 2.5).

### 14.1 A screen that binds no filters could be described but not driven
**Symptom** `describe Q2241UM00` listed the screen's visible inputs and then
said "these cannot be set with --set; the screen fills them in code".
**Cause** Filters were only ever written through their dataset. A control
with no binding had nowhere to write to — although the mechanism to drive it
already existed a few files away, in the search box (Phase 8.2).
**Fix** `type_text()` clicks the control, clears it with Ctrl+A/Delete, sends
per-character keyDown/char/keyUp, commits with Tab, and then **reads back
what the control shows**. `Screen.apply()` picks the mechanism from the
control: dataset if bound, keys if not.
**Lesson** "Cannot" was really "not wired up". The capability had been built
for one control and never generalised.

### 14.2 The date rule knew two column names
**Symptom** `describe` on screens storing `planYmd` or `stdYm` printed
"this screen has no from/to date filter - skipped", and the run then used
whatever date was already in the box.
**Cause** The match was `*fromdate*` / `*enddate*` and nothing else.
**Fix** Date fields are recognised by whole *words* in the column or label
(`date`, `ymd`, `ym`, `dt`, `period`, `day`) or by Nexacro's own control type
(`msk`, `cal`) holding 4, 6 or 8 digits. From/to is matched the same way.
Where there is no from/to pair and several single date fields, only the first
is set and the rest are **named in a warning**, rather than a guess being
made about what each one means.

Two traps found while writing that rule, both now covered by offline tests:

- **`paramVendorCode` contains the letters "end"**, so a substring match
  classified a vendor code as the period's end date and would have written
  today's date over it. Only whole camel-case words count now.
- **Not every period field is eight digits.** `stdYm` holds `YYYYMM`, and
  writing eight digits into one is the same class of mistake as writing
  `2026-09-07` into a `YYYYMMDD` field (Phase 12.3): accepted, and then the
  query answers something else. `fit_date_to_field()` matches the width the
  field is already storing — the screen telling us which it wants.

### 14.3 The result grid was a silent coin toss
**Symptom** None, which is the point. On a master-detail screen the exporter
took "the biggest visible grid".
**Cause** A heuristic with no confidence measure attached.
**Fix** The pick is still the biggest visible grid, but when a second grid is
within 40% of its area the run **says so** and `--grid` settles it outright.
An unmatched `--grid` now fails with the list rather than falling back.

### 14.4 One hardcoded Org tree, and a tick that survived the run
**Symptom (a)** `--division` worked only on screens carrying
`OrgCategory_GDS.dsCatCommonTreeNodeDVO`. The left panel offers Org / Prod /
Fac / Proc and each tab has a tree of its own.
**Fix (a)** Trees are found by **shape** — any dataset with a `commonName`
column and a `_checked` flag — and the one to use is chosen by *data*: the
tree that actually contains the name asked for. Picking the first or the
biggest is a guess that fails silently on a screen with four.
**Symptom (b)** Not yet observed, and being fixed pre-emptively because it is
mechanically identical to 12.1: a tick lives on the screen, the screen lives
behind its tab, so a division ticked by one run is **still ticked** for the
next. A later run asking for MOBILE would have queried MOBILE *and* VD and
answered confidently.
**Fix (b)** `tick_org(..., exclusive=True)` clears ticks the run did not ask
for and prints what it cleared.

### 14.5 Opening a screen assumed it was built
**Symptom** "the screen's forms did not appear after opening".
**Cause** `run_one()` read the screen once, immediately after activating the
tab. Nexacro builds its UI in JavaScript long after the tab exists — this is
rule 3.1, broken in our own code.
**Fix** `open_screen()` polls discovery until the screen reports forms, with
a generous cap. It also **activates first and checks it worked**, and reuses
a screen that is already open instead of retyping its code into the search
box one character at a time.

### 14.6 Two copies of the inquiry wait
**Cause** The nightly job and the generic runner each had one. That
duplication is exactly how Phase 10.4's lying row count happened: one copy
was fixed and the other was not.
**Fix** One `poll_inquiry()`, taking the screen code and dataset to watch.
`gmes_daily_prodplan.py` keeps its function names — `gmes_demo.py` calls
them — but they are now three-line wrappers. What stays specific to that job
is only what it genuinely knows about its own screen: which datasets, and
that a row with no `poNo` is a LINE SUM / PROC SUM subtotal.

### 14.7 Open item 8 closed — sign-in is retried
Session expiry produced no SSO window on a first attempt and signed in
normally on the second (Phase 11.4). `core.sign_in()` retries once before
reporting failure, so one expired session no longer takes a whole batch with
it.

### 14.8 Also
- `--dry-run` applies everything and stops before Inquiry, so a setup can be
  checked against a live screen without running a query.
- `--verify COLUMN[=VALUE]` refuses to export unless the returned rows carry
  the value asked for — the generic form of `verify_result_date()`. Without
  it, a run that set a date now *reports* the date-like columns it got back
  instead of silently trusting them.
- `--manifest PATH` writes the run as JSON. The summary was printed text
  only, which is awkward to schedule against.
- `--close-tabs` closes each screen when it is done; screens otherwise
  accumulate for the whole batch, each holding its filters and its result
  set. The close control is looked for **inside** the tab and matched by
  class or id, and if there is no such control it reports that rather than
  clicking at a guessed position (rule 3.9).
- A bound write that reads back **empty** is now fatal; one that reads back
  *different* is reported as "G-MES reformatted it", because a mask
  reformatting a date is not a failed write and must not abort a good run.

### 14.9 What is verified, and what is not
`tests/test_gmes_core.py` — 37 offline tests over every decision the core
makes about a screen it has already read: filter matching, date detection and
width, grid choice, JS template balance. Green, alongside the 31 N-ERP tests.

**Not verified: everything that needs a browser.** There is no G-MES mock, so
`type_text`, the generic tree ticking, `--dry-run`, `--close-tabs` and the
whole pipeline have been run against nothing but their own unit tests. The
live confirmation is the next step, and until it happens this phase is code,
not evidence.

---

# Phase 15 — the basic workflow, and memory that cannot lie

The request, deliberately narrow: type a UI number, a division and two dates,
press Enter, get a verified Excel file. **No automatic date selection** —
"yesterday" and date arithmetic come later, once the manual path is stable.

    gmes run P1112UM00 --division VD --from 20260909 --to 20260909

### 15.1 There was no way to ask for a date RANGE
**Symptom** `--date` wrote the same value into both ends of the period. A
run covering 1–10 September could not be expressed at all.
**Fix** `--from` and `--to`, each normalised and rejected if it is not a real
calendar date, and refused unless both are given. `set_date_range()` puts one
value in each end.
Two cases it will not guess at, because guessing is how the wrong period gets
queried without anything looking wrong:
- a screen with **one** date field and two different dates → stops, and says
  the field is single;
- a value given for an end the screen does not have → stops, and lists the
  date fields it does have. Setting one end and querying a period nobody
  asked for would be worse.

### 15.2 Nothing was remembered, so every run re-guessed
**Symptom** Discovery gets the mechanics right every time, but two questions
are not mechanical: on a screen with several date fields, which one is
"from"? With two grids, which is the result? The tool re-answered by
heuristic on every run, and a heuristic that is right today can be right for
the wrong reason tomorrow.
**Fix** `gmes_profile.py`. After a run that opened, applied, verified,
queried, exported **and** checked the file, the answers are saved to
`screens/<CODE>.json`.

What is deliberately **not** saved, and why:
- **no coordinates** — a rect is valid only between the `evaluate` that
  produced it and the click that consumes it (menus pre-render at
  `y = -99984`);
- **no window ids** — renumbered on every open, so they are stale before
  reuse (gotcha #7);
- **no dataset contents** — a form tree carries live session tokens in an
  ordinary-looking `dsAnyframeDVO` (gotcha #26), so fields are copied out
  **one at a time by name**. That is an allowlist, and it is the point: a
  recorder that serialised "whatever was discovered" would write credentials
  to disk.

What is saved is only names that are stable by construction — screen code,
dataset, column, control, tree entry, grid dataset — every one of which is
re-resolved against the live screen before it is used.

### 15.3 A profile is never repaired silently
Every run fingerprints the screen (a digest of every filter, grid and unbound
input, by name) and compares it with the one stored. Three outcomes:

| | |
|---|---|
| identical | replay the saved answers |
| a referenced control has gone | **refuse to replay**, name what moved, read the screen from scratch |
| something else changed | same — say so, and rediscover |

It never re-matches quietly. This is the direct lesson of Phase 10.4, where a
remembered dataset name made a run report 875 rows for a screen that had
returned 17: the export was right, the log lied, and nobody checked.
`--relearn` discards a profile outright.

### 15.4 "The download succeeded" meant three different things
**Symptom** The export step confirmed that a file *appeared*. A zero-byte or
stub file arrives looking exactly like a real one.
**Fix** `check_download()` — the file exists, and it is over 512 bytes.
That is as far as verification can go for the `.xlsx`: it is NASCA-DRM
encrypted, so nothing can read it and nothing can confirm what is inside
(open item 2). The CSV written from the data layer is the only real evidence
of content, which is why both are produced.

### 15.5 Verified
46 offline tests, including the profile drift cases — a renamed date field, a
vanished grid, an added filter elsewhere, and a check that a saved reference
carries no value and no id. Green, with the 31 N-ERP tests.

Still **unverified against live G-MES**: the whole browser-driven path, now
including profile save and replay. Open item 9 stands.

---

# Phase 16 — the first live run: 90 seconds of silence

The first attempt at the basic workflow against real G-MES. It did not get
as far as the screen.

### 16.1 The answer was on the screen the whole time
**Symptom** `gmes run P1112UM00 ... --dry-run` sat with no output for over
90 seconds and had to be interrupted. The G-MES login page was showing
**"Auth bad credentials"** in red the entire time.
**Cause** `wait_for_sso_window()` watched for exactly two things: a Samsung
ADFS window, or a completed sign-in. G-MES's third answer - refusing, and
writing the reason onto its own login form - matched neither, so the wait ran
its full 45 seconds and reported "the Samsung SSO window never opened", which
is true and useless. The error text was read only *after* that timeout, in a
different branch.
**Fix** `login_error()` reads `divLogin.form.staErrMsg`, and it is polled
*during* the wait, not after it. A refusal now stops the run in a few seconds
and prints what G-MES actually said.
**Lesson** We had already learned to wait for the thing we want (rule 3.2).
This is the other half: **also watch for the system saying no.** A wait that
can only end in success or timeout turns a clear rejection into a hang.

### 16.2 The retry doubled the damage
**Symptom** 45 seconds, then 45 more. The ~90s was Phase 14.7's retry doing
exactly what it was told.
**Cause** `sign_in()` retried *any* non-zero result. A retry is right for the
transient case that motivated it (an expired session producing no SSO window,
Phase 11.4) and wrong for a credential rejection, which will answer
identically - and which walks a corporate account towards being locked.
**Fix** `gmes_login.main()` now returns `OK` / `FAILED` / `REJECTED`, and
`sign_in()` retries `FAILED` only. "No saved credentials" and an ADFS refusal
are `REJECTED` too.
**Lesson** A retry needs a reason, not just a failure. Retrying something
that cannot succeed costs the user time and can cost them the account.

### 16.3 Also
The 120-second wait after submitting to ADFS had the same shape - it polled
only for "signed in" and would have spent the full two minutes on a sign-in
already refused in the first second. It now watches for the refusal too.
`gmes_login.py --status` prints the login page's message when there is one.

### 16.4 Open, and not ours to fix
The user reports that signing in **by hand** on the same page also failed
with the same message. If that was the ID/password form rather than the
**AD SSO Login** button, it proves nothing about SSO - they are different
paths. Unresolved until the account itself is checked; recorded as open
item 11 rather than guessed at.

---

# Phase 17 — it works, and three bugs the live run found

The first end-to-end run against real G-MES. **It worked**, and open item 9
is closed:

```
run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
  division : VD
  dates    : paramFromDate=20260909, paramEndDate=20260909
  inquiry  : 801 rows in 8.7s
  verified : planYmd = ['20260909']
  excel    : ...xlsx  78.9 KB  [DRM]
  csv      : ..._data.csv  801 rows
```

Repeated for 20260908 (880 rows) and 20260901–02 (1485 rows). Same date
twice gave 801 both times.

**Open item 11 was not a defect at all.** Sign-in succeeded first time as
'Mohamed Fawzy' — the saved session signed straight back in, no SSO window
needed. The "Auth bad credentials" seen earlier came from the user's own
manual attempt on the **ID/password form**, which is a different door from
the **AD SSO Login** button this tool uses. Phase 16's fail-fast work stands
on its own merits, but it was fixing the symptom of someone else's failure.

### 17.1 `--status` crashed instead of reporting
**Symptom** `gmes_login.py --status` with no browser running printed a
40-line urllib traceback ending in `ConnectionRefusedError`.
**Cause** `gmes_tab()` raises a `RuntimeError` written for a person to read —
"Cannot reach the automation browser… Start it with: python gmes_login.py" —
and `main()` called `connect_gmes()` outside any `try`. The good sentence was
there, buried under the traceback.
**Lesson** A diagnostic command that crashes when things are wrong is a
diagnostic command that only works when you do not need it.

### 17.2 The shell's own panels were being offered as the report's
**Symptom** `describe P1112UM00` listed **22 category trees**. The screen has
one. It also listed `grdMyMenuGrp` and `grdWidgetList` among the candidate
result grids.
**Cause** `SHELL` excluded frame-owned forms from the *binds* walk but not
from the *grid* walk, and the tree walk had no exclusion at all — it matched
by shape, and the My Menu datasets carry a `commonName` column too. The
pattern also missed `TopMenu`, `LeftMenu`, `PortalMain` and `MyMenuSub`.
**Fix** One `SHELL` pattern applied to binds, grids and trees alike; trees
with zero rows are dropped. 22 trees → 1, with `ticked now: ['VD']`.
**Lesson** Shape alone is not identity. `commonName` says "tree-like", not
"organisation tree".

### 17.3 The memory erased itself on every run — the serious one
**Symptom** Two runs of the same screen a minute apart:
`changed : the screen's controls have changed since this was learned`, and
the profile was thrown away. It relearned and discarded, every time.
**Cause** The fingerprint measured three things that move without the screen
changing:
- **unbound inputs**, which are collected only when *visible* — visibility
  moves with scrolling and late-rendering panels;
- the **control name** of a bound filter, when one column can be bound to
  several and the recorded one is whichever was visible;
- **`grdPrnMpp__EXCEL__`**, a throwaway grid the Excel export clones from the
  one it is exporting and leaves behind — so every export changed the screen's
  shape.
**Fix** Fingerprint only what a profile can actually refer to — bound filters
by `dataset.column`, and grids by dataset, **as sets**. `__EXCEL__` clones are
dropped at discovery.
**Lesson** A staleness check must measure exactly what the memory depends on.
Measuring more is not more careful: a memory that erases itself on every run
is worse than no memory, because it also cries wolf, and the next person to
see that warning will have learned to ignore it.

### 17.4 Verified
Learn, then replay immediately after an export:
```
RUN 1  inquiry 801 rows   learned  : saved to P1112UM00.json
RUN 2  learned : learned 2026-09-10 09:34:07  from=paramFromDate
                 to=paramEndDate  grid=dsMasterProdPlan
       inquiry 801 rows
```
49 offline tests green, including the three new drift cases.

### 17.5 Still true, and worth repeating
The CSV carries **801 rows including LINE SUM / PROC SUM subtotals**. The
generic exporter drops only completely empty rows, because on an unknown
screen there is no key column to judge by (gotcha #33). The grid's own visible
total is lower. The nightly Production Plan job, which does know its screen,
drops rows with no `poNo`.

---

# Phase 18 — a front end that shows which phase it is in

The request: make `GMES_Workflow.bat` something a non-technical person can
use, and make it obvious **when the tool is learning a screen and when it is
replaying one**.

### 18.1 The two phases were invisible
The record/replay design was real but only discoverable by reading log lines
after the fact. The front end now states it *before* the work, from the
profile on disk:

```
   RECORDING - P1111UM00 is new.
   It will work the screen out as it goes, and remember it
   afterwards IF the whole run succeeds.
```
```
   REPLAYING - P1111UM00 was learned on 2026-09-10 09:50:13.
   It will check the screen still matches, then reuse what it knows.
```

The run itself is narrated as numbered steps in plain words. `core.run_screen`
already reported everything as `key : detail`; a `Narrator` maps those keys to
sentences. An unrecognised key is printed raw rather than dropped — a display
layer must never be the reason something goes unseen.

### 18.2 Two things printed straight past the front end
**Symptom** A bare `result: P1111UM00 - Production Plan by Model` and the
sign-in tool's full banner appeared in the middle of the formatted output.
**Cause** `gmes_open_screen.open_screen()` called `print()` directly, and
`gmes_login.main()` prints its own report.
**Fix** `open_screen()` takes a `log` callback and uses the same
`key : detail` shape as everything else. The front end captures the sign-in
output and shows one line — **and prints the whole captured text the moment
anything fails**, so a quieter front end never costs a diagnosis.

### 18.3 The memory knew which tree to use and was not asked
**Symptom** On P1111UM00, every replay warned `2 category trees contain 'VD';
using OrgCategory_GDS...`. The profile had recorded that exact tree on the
first successful run.
**Cause** `select_org()` re-decided from the data every time. The saved answer
was written and never read.
**Fix** A `prefer` hint, passed from the profile. It is only a preference: if
the tree that worked before does not contain what is being asked for now, the
data-driven choice still applies, so asking for a division that lives
somewhere else is not broken by the memory.
**Lesson** Saving something proven and then not consulting it is the same
defect as not saving it — with the extra cost of looking like it works.

### 18.4 Verified live, on a second screen
`P1111UM00` (Production Plan by Model) had never been run. Its date columns
are `paramFromDate` / **`paramToDate`** — not the `paramEndDate` of
P1112UM00 — so the word-based date matching of Phase 14.2 was exercised for
real rather than only in tests.

```
RECORD  20260909  219 rows   learned -> P1111UM00.json
REPLAY  20260908  286 rows   using memory
REPLAY  20260907  312 rows   using memory, no tree warning
```
Excel and CSV delivered each time, `planYmd` correct each time.

### 18.5 Two more found by watching a demo run
**A time and a model code were reported as dates.** Without `--verify`, the
run prints the date columns that came back. On the Production Plan result
that was `{'planYmd': [...], 'prodTime': ['000025'], 'planWeekno':
['202636'], 'modelDesc': ['65856560']}` — under a heading promising dates.
`date_like_columns()` asked only whether every sampled value was six or eight
digits. It is the same mistake as 17.2, in a different place: **shape is not
identity**. The column now has to be NAMED like a date as well.

**The question numbers skipped.** On a screen with no date fields the "To
date" question is never reached, so the prompts counted 1, 2, 3, 5. A gap in
a numbered list reads as something having gone wrong. Numbers are assigned as
questions are actually asked, and a re-ask after a bad answer keeps its
number rather than inventing a new one.

### 18.6 Three screens, three shapes, all working
| Screen | Shape | Result |
|---|---|---|
| `P1112UM00` Production Plan by Order(Line) | 8 bound filters, `paramEndDate` | replay, 800 rows |
| `P1111UM00` Production Plan by Model | 7 bound filters, **`paramToDate`** | replay, 219 rows |
| `M4151UM00` Work Calendar (MRM) | **0 bound filters, no date fields at all** | record then replay, 1112 rows |

The third is the interesting one: a different module, binding nothing, with
Year/Month combos instead of a date range. It was opened, filtered by
division, queried, exported and learned on the first attempt, and the run
correctly showed no date step at all rather than inventing one.

Its first run warned `3 category trees contain 'VD'`; the replay did not,
because 18.3's `prefer` hint had recorded which tree worked.

---

# Phase 19 — a demo that looked hung, and the login that really was

The request: run `GMES_Workflow.bat` **visibly**, beside Chrome, with the
answers typed in on screen, for a management demonstration.

### 19.1 It looked hung because nothing was drawn for a minute
**Symptom** "it hangs and never run".
**Cause** The script signed in first with `& python gmes_login.py | Out-Null`.
From cold that starts Chrome, clones nothing but still takes the best part of
a minute — with the output swallowed, so the screen stayed completely empty
before a single window appeared.
**Fix** Check whether the browser is already up, say which case it is in, and
never swallow the sign-in output. The sign-in is also a separate step now, so
the audience sees Chrome arrive rather than watching a blank screen.
**Lesson** For anything a person watches, silence *is* a failure. The work
was progressing correctly and it still had to be called a bug.

### 19.2 The window handle was always zero
**Symptom** `MainWindowHandle : 0`, so the demo could not find, position or
focus the tool's window.
**Cause** Started as a plain `cmd.exe`, a console on this machine opens
inside **Windows Terminal**. The window belongs to `WindowsTerminal.exe`, not
to the process `Start-Process` returns. Worse for a demo: the command can
land as a new **tab** in a terminal window that is already open, so bringing
"it" to the front shows whichever tab is selected.
**Fix** Launch through `conhost.exe`, which gives a classic window of its
own every time, and find that window by its **title** rather than by process.
Measured both ways: plain `cmd` → `WindowsTerminal hwnd=1510290`;
via conhost → `cmd hwnd=1247060`.

### 19.3 The safety guard earned its place before the demo ran
`SendKeys` goes to whatever window has focus, and Windows can refuse a
foreground change requested by a background process. The first typing test
hit exactly that and **refused to type** rather than typing `P1112UM00` into
whatever the presenter had open. After the conhost fix, the same test typed
all four values and read them back intact:
`TYPED OK -> P1112UM00|VD|20260909|20260909`.

### 19.4 The real blocker: the stored password is stale
Every successful sign-in today reported **"No SSO window was needed - the
saved session signed in."** The saved password was never used; a session
cookie surviving in the profile copy did the work. Once the browser was
closed at the end of the earlier demo that session was gone, and the next
sign-in had to authenticate for real:

```
Signing in as 'm.labib' via AD SSO...
ERROR: G-MES refused the sign-in and says: 'Auth bad credentials'
```

The diagnostic screenshot confirms it: the G-MES login page, the message in
red, and no Samsung ADFS window ever opened.

This also explains Phase 17's conclusion, which was **half wrong**: sign-in
was not proven working that day, only *session reuse* was. Recorded as open
item 12.

**No retry was attempted.** Repeated failures against a corporate directory
are how an account gets locked, and `sign_in()` already refuses to retry a
`REJECTED` result for that reason (Phase 16.2).

---

# Phase 20 — the false rejection, and what it cost

### 20.1 A message on a page was allowed to decide something
**Symptom** Three separate diagnoses in one session blamed the account:
"the stored password is stale", "the profile copy has expired", "the account
needs IT". The user was asked to sign in by hand. **All of it was wrong.**
**Cause** Phase 16 added fail-fast rejection detection, and it read a message
on the login form as authoritative. It was not:

- the message is often **left over from an earlier attempt** — including one
  the user made themselves, and it survives on the page;
- the Samsung ADFS window can arrive **after** it. Observed directly: the run
  gave up at 6s, and an inspection minutes later found the ADFS sign-in page
  open with its ID and password boxes empty and waiting. The automation had
  never got as far as trying the password at all.

Raising the grace to 22s did not fix it, because the flaw was not the number.
**Fix** The message no longer decides anything. The rule is now what it
should always have been, and the user put it plainly: *if it says an error
but you are already logged in, ignore it and carry on.*

```
signed in                     -> done, whatever the page says
an SSO window appeared        -> go and fill it in
neither, for the whole wait   -> a real failure, and NOW quote the message
```

The same correction was applied to the 120-second wait after submitting to
ADFS, which had the identical shape.
**Lesson** A symptom is not a diagnosis. Reading an error message as a
verdict turned three sound components — the password, the profile, the
account — into suspects, and cost the user a manual sign-in they should
never have been asked for. When a stronger signal exists (*are we actually
signed in?*), check that first and let nothing else overrule it.


### 20.4 What actually broke the automatic sign-in
Worth stating plainly, because two of the day's own actions caused it.

**Symptom** "The sign in still not automatic - it was working perfectly
before."
**Cause, in order:**
1. The instant sign-in everyone had been enjoying came from a **live G-MES
   session inside the profile COPY** - never from the stored password.
2. `--refresh-profile` overwrote that copy with the user's real Chrome
   profile, **destroying the working session**. The refresh was meant to
   help; it removed the only thing that was working.
3. With no session, AD SSO had to authenticate for real - and the Phase 16
   false rejection aborted it after six seconds, every time.
4. Those failures were then blamed on the password, the profile and the
   account. All three were fine.
**Fix** 20.1 removed the false rejection, and `--refresh-profile` now warns
that it destroys the session before it does it.
**Proof** With the message no longer deciding anything, the same command on
the same browser - with `'Auth bad credentials'` still displayed on the page
- signed straight in:
```
Signing in as 'm.labib' via AD SSO...
No SSO window was needed - the saved session signed in.
Signed in as 'Mohamed Fawzy'.
```
**Lesson** A repair aimed at a misdiagnosis is not neutral. Refreshing the
profile was a reasonable-sounding step that made the real problem worse and
hid it, and the evidence for the original diagnosis was itself produced by
the bug.
### 20.2 Also, from the same session
- **`--refresh-profile`** now exposes what `clone_user_profile(refresh=True)`
  could always do: re-copy the user's real Chrome profile, so the automated
  browser gets a current session and Chrome's saved logins. Every Chrome
  window must be closed first, because Chrome keeps those files locked.
- **`cdp_common.close_browser()`** closes the automation browser through its
  own DevTools endpoint — never `taskkill /IM chrome.exe`, which would take
  every window the user has open (CLAUDE.md 2.6).
- **`gmes_tab()` was picking the SSO window.** It matched "gmes" anywhere in
  the URL, and the ADFS address carries a long base64 `SAMLRequest` that
  happened to contain those four letters. Everything downstream then read the
  wrong document. It matches on the host now, and excludes `secsso.net`.
- **`--assist`** waits for a person to sign in by hand, for the case where
  SSO genuinely will not complete. It detects a browser that has been closed
  rather than polling a dead endpoint for its full seven minutes.
- **`gmes_ui.py`** carries the terminal presentation, degrading to plain
  ASCII when the console cannot do colour or box-drawing. Presentation never
  decides anything.
- **`HOW_TO_USE.md`** is the one-page guide for someone who just wants to run
  a report.

### 20.3 The demo script, and why it is parked
`Demo_ForManagement.ps1` drives the tool in a visible window with real
keystrokes. Three real defects were found and fixed while building it — a
silent minute that looked like a hang, console windows owned by Windows
Terminal so their handle was always 0, and a window handle that goes stale
the moment conhost hands over to the hosted command. Its focus guard also
worked exactly as intended, refusing to type a screen code into whatever
window happened to have focus.

It is left in the repository, unfinished: the last failure was the stale
handle, now fixed but unverified. The tool itself does not depend on it.

---


---

# Phase 21 — recording that actually shows you the screen

### 21.1 The first run asked about filters nobody had looked at
**Symptom** The user: *"the record ui must discover the new UI number the
user uses for the first time - it does not know what the filters or their
names are, so it must list the main filters on the left panel and the
available options for each, so the user can choose."*
**Cause** The questions were asked BEFORE the screen was opened. The tool
knew nothing about it and neither did the person, so both were guessing.
It asked Work Calendar for a From and a To date - a screen with no date
fields at all - and asked for a division without ever showing which
divisions exist.
**Fix** The screen is opened straight after the UI number is given, and on a
screen being learned the tool now prints what it has before asking anything:
the result table, the date fields it will use (or plainly that there are
none), the other filters with their current values, the real list of
divisions, and the left-panel options with which are already on.

The questions then adapt to the screen:
- no date fields -> the date questions are not asked at all;
- no organisation list -> the division question is not asked;
- a division that is not on this screen is rejected, with the near matches.

### 21.2 Left-panel options are decisions, so they are remembered
The panel choices - `Plan Date` against `Create Date`, `STD` against `PLANT`
- change what the query MEANS, and nothing on the screen records which one a
report is supposed to use. Both look correct and return different answers
(Phase 11.1). They are now offered while a screen is being learned, saved
into its profile, and re-applied on every replay unless the run names its
own.


### 21.4 The three things that made it look broken
All reported in one screenshot: the tool sitting on "Signing in to G-MES..."
while the browser showed the login page.

**It was not frozen - it was silent.** `sign_in_quietly()` captured the
sign-in output and printed one tidy line at the end. Signing in takes up to a
minute when the session has expired, and for all of it the screen said
nothing. This is the same mistake as Phase 19.1, made again three phases
later, in a different file. Nothing is captured now.

**A tab that was still navigating.** The Phase 20 host-matching rewrite
returned "any page" when no G-MES tab was found yet - and straight after
Chrome starts, that is a tab about to be replaced. Attaching to it died with
`WebSocketConnectionClosedException` out of `Runtime.enable`. `gmes_tab()`
now WAITS for the real tab, and `connect_gmes()` re-resolves it on each of
four attempts rather than retrying the same doomed one.

**The popup closer spun.** One sign-in reported closing `S9502UP01`
twenty-three times: each pass re-found the popup it had just clicked and
clicked it again, and `while ... or closed` plus a deadline pushed out 8s per
pass meant it could not stop. The count is now checked after every pass, and
two passes that fail to reduce it end the loop - the clicks are not working
and going round again only burns time.


### 21.6 The freeze was a dead socket, ignored in a loop
**Symptom** The tool sat on *"Waiting for the GMES app to build itself..."*
while, beside it, the browser was showing the G-MES login page perfectly.
**Cause** `wait_for_login_or_session()` wrapped its checks in
`except Exception: pass`, with the comment "still navigating; the socket or
document is in flux". That is true for a second or two. It is not true when
the tab we attached to has been REPLACED during the page load: the socket is
dead, every check afterwards raises, every raise is ignored, and the loop
runs its full four minutes having learned nothing. The one line it printed
never changed, so it looked frozen - and it effectively was.
**Fix** Three failures in a row are read as a lost connection rather than a
busy page: the socket is closed and reattached. It also prints how long it
has been waiting every 15 seconds, so a slow load is visibly a slow load.

The same fault, one page along: `complete_sso()` attached to the ADFS window
once and evaluated in a loop, and ADFS redirects several times while it
settles. The first cold start after the fix above got as far as
`SSO window opened; filling in the saved credentials...` and then died with
`ConnectionAbortedError [WinError 10053]`. It reattaches now, and treats the
window disappearing as a completed sign-in rather than an error.

**Lesson** `except Exception: pass` inside a polling loop cannot tell "not
ready yet" from "will never be ready". Wherever it appears, ask which of the
two is being swallowed - here it was both, in three separate places, and the
symptom every time was a tool that looked frozen while the browser looked
fine.

**Verified, from a fully closed browser:**
```
Browser: started
Signing in as 'm.labib' via AD SSO...
No SSO window was needed - the saved session signed in.
Signed in as 'Mohamed Fawzy'.
Popups closed: ['S9502UP01', 'S9502UP01']        <- was 23
                                                    35s cold, then
REPLAYING P1112UM00 -> 800 rows, xlsx + csv       51s end to end
```
### 21.5 The mode is now chosen, not inferred
The user asked to pick the mode at the start rather than have it decided:

```
  1. Record or Replay?   type R or P
```

RECORD opens the screen and shows everything before asking. REPLAY asks only
for the UI number, the filter values, and Enter. A disagreement is stated
rather than silently resolved - REPLAY on a screen never used says so and
records it instead; RECORD on a known screen warns that it replaces what is
already known.
### 21.3 The saved credentials were held but never used
**Symptom** *"It stopped again on the login screen - you must use my saved
credentials."*
**Cause** Two things. G-MES has its own ID and password form beside the AD
SSO button, and the automation never touched it. And every way AD SSO could
fail **returned immediately** - so even after the fallback was written, it
could not be reached.
**Fix** `direct_login()` fills `edUserID` and `edPassword` through Nexacro's
own components (a raw `.value` on the inner `<input>` looks right and submits
nothing, because the button reads the component) and presses Login. Every
AD SSO branch now falls THROUGH to it instead of returning, and a failed SSO
skips the 120-second wait rather than serving it out.

Confirmed live, without submitting: `{'ok': True, 'user': 'm.labib',
'pw_set': True}` - the read-back returns the ID and a boolean, never the
password.
**Lesson** A fallback that cannot be reached is not a fallback. The code was
written, reviewed and committed before anyone checked that control ever got
to it.
---

---

# Phase 22 — the blank page: G-MES fills its own storage until it cannot start

The tool sat waiting while the browser showed a spinner on a blank page. It
was neither the login nor the automation.

### 22.1 The application never started, and nothing said so
**Symptom** `still waiting for G-MES to finish loading (15s)...` against a
blank white page with a spinner. Reloading did not help; 61 seconds of
polling after a hard reload showed no change. A brand new browser did the
same.
**Cause, read off the page rather than guessed:**
```
ready: complete   nexacro: True   app: False   divs: 3   text: ''
```
The document had finished, the Nexacro library had loaded, and
`nexacro.getApplication()` was **empty** - the application object was never
constructed. No failed requests. No HTTP errors. Nothing pointing anywhere.

The console had it:
```
QuotaExceededError: Failed to execute 'setItem' on 'Storage':
Setting the value of '1789029501234http://seegmes4.../nexacro/engine'
exceeded the quota.
```

**G-MES caches its entire Nexacro engine in `localStorage`**, under a key
made of a timestamp and the engine URL - and it writes a new one on load
without ever removing the old. Measured when this happened:

| | |
|---|---|
| localStorage entries | 102 |
| total size | **5.00 MB** - exactly the per-site limit |
| copies of the engine | **52**, ~99 KB each |

So its own bootstrap throws, and the app cannot start. A reload cannot fix it
because the storage is still full. **Automation reaches this far sooner than
a person does**, because it opens the page repeatedly all day.

**Fix** `prune_nexacro_cache()` removes the stale copies and keeps the
newest. Run by hand at the time: 51 removed, **4.94 MB freed**, and after a
reload the application built itself in under four seconds - already signed
in, so nothing else was lost. `wait_for_login_or_session()` now does this
automatically: if neither control has appeared after 20s AND
`app_is_built()` is false, it reports the storage state, sweeps the cache
once, and reloads.
**Lesson** "Blank page" is not a diagnosis, and a slow page and a page that
has failed to bootstrap look identical from outside. The difference was one
question - does the application object exist? - and the answer was one
console line away for the entire hour spent blaming the login.

### 22.2 It refused to start because the user's own Chrome was open
**Symptom** *"Chrome is open but not under automation control. Close every
Chrome window (check the system tray) and run this again."*
**Cause** `ensure_browser()` treated any running `chrome.exe` as a conflict.
The rule it came from - "Chrome will not hand over a profile already in
use" - is about the **same profile directory**, and the automation
deliberately runs on a *copy* precisely to avoid that.
**Fix** Removed. Measured directly: with **30** of the user's own chrome.exe
processes running, `launch_chrome_with_user_profile()` returned normally and
the debugging port opened. It now says the open browser is fine and carries
on; if the port genuinely does not open, the launcher's own error already
covers the case the guard was aimed at - a stale Chrome still holding the
copy.
**Lesson** A guard copied from a neighbouring rule, never tested against the
thing it was guarding. It cost the user every window they had open, every
run, for nothing.
---

---

# Phase 23 — a session, not a single shot

Three things asked for after using it properly, and one bug found while
building them.

### 23.1 It closed after every report
**Symptom** Finishing a run - or mistyping anything - ended the program, so
the next report meant starting again from the sign-in.
**Fix** `one_run()` does one report and RETURNS; `main()` loops, asking
"Another report?" A cancelled run, a wrong number and a failed query all come
back to the questions instead of exiting. Nothing inside a report can end the
session any more.

### 23.2 A wrong UI number killed the session
**Symptom** A number that does not exist was accepted, sent to the browser,
and the run died there - the typo cost a whole sign-in.
**Cause** Nothing validated it. The catalogue of all 809 screens this account
can open is held client-side, so it could have been checked in milliseconds.
**Fix** `question_screen()` looks the code up first. A miss says *"There is
no screen 'P9999ZZ99'. Please try again."*, lists anything close, and asks
again. The same discipline is now on the division (*"'X' is not on this
screen"*) and the dates (*"... Please try again."*).

### 23.3 The recording remembered the fields and forgot the values
**Symptom** The user's point exactly: a screen recorded an hour earlier still
asked for the division, the dates and the filters. *"How does it forget? It
must have a memory in JSON so it never forgets any recording ever."*
**Cause** The profile stored the *identities* - which box is the from-date,
which table holds the results - and nothing about what was typed into them.
Correct as far as it went, and useless as a memory: the whole promise of
recording is not typing it again.
**Fix** The profile now carries a `values` block (division, from, to, named
filters) written on every successful run, and every question offers it as the
default. REPLAY also LISTS the screens already recorded, newest first, with
what was used last time, and takes a number:

```
    Screens already recorded:
      1  P1112UM00   Production Plan by Order(Line)   division=VD, from=20260909, to=20260909
      2  P1111UM00   Production Plan by Model
      3  P2237UM00   Manufacturing personnel management
      4  M4151UM00   Work Calendar

  REPLAYING - P1112UM00 was learned 2026-09-10 12:02:54
    [i] last time: division=VD, from=20260909, to=20260909  (press Enter to reuse each)
```

Pressing Enter through every question now reproduces the last run exactly -
verified: 800 rows, xlsx + csv. The files are plain JSON in `screens/`, so
nothing is forgotten between sessions.
`screens/` stays git-ignored: a filter value can be a production order.

### 23.4 The bug this introduced, caught immediately
**Symptom** With input exhausted, the tool printed *"2. Which screen?"*
thousands of times in a second.
**Cause** `ask()` turned `EOFError` into the default value. Once stdin ends,
every re-ask loop got the empty default, rejected it and asked again -
forever. Harmless with a keyboard attached; fatal for anything scripted.
**Fix** A blank line and a closed stream are different answers. Blank is an
answer; closed raises `InputClosed`, which ends the session cleanly. Measured
after: 2 seconds instead of never.
**Lesson** The re-ask loops added in 23.2 were the right fix and they turned
a swallowed exception into an infinite one. Adding a retry to a loop means
checking what it does when the input it retries for cannot arrive.
---

---

# Phase 24 — replay that does not ask, and a log to read afterwards

### 24.1 REPLAY was still asking for everything it knew
**Symptom** *"How are we in the replay and still the tool asks me which
division? It should already be done in the recording stage."* Correct, and
the screenshot showed why it looked worse than it was: `P2237UM00` had been
recorded at 11:51, before Phase 23 added the values, so it had nothing to
offer and asked cold.
**Cause, in two parts:**
1. Even with values, REPLAY still *asked* each question with the remembered
   value as a default. Better than nothing and still the wrong shape - the
   point of recording is not to be asked.
2. Profiles written before Phase 23 had no `values` block at all.
**Fix**
- REPLAY with known values now **shows** them and asks one thing:
  `Run it?  Enter to run, or type c to change something`. One keypress runs
  the whole report; only wanting a different day requires typing.
- `last_values()` recovers what it can from the `proved.command` string,
  which every profile has recorded since Phase 15. All four existing
  profiles produced their division and dates immediately - nobody had to
  re-teach anything.
- A profile with genuinely nothing recoverable says so, asks once, and keeps
  it from then on.

**Verified** - Replay, three keypresses total (Enter, `3`, Enter):
```
  3  P2237UM00  Manufacturing personnel management  division=VD, from=20260909, to=20260909
REPLAYING - P2237UM00 was learned 2026-09-10 11:51:01
REMEMBERED SETTINGS   Division VD   Period 20260909 to 20260909
  Run it?  Enter to run, or type c to change something
  ...  1573 rows in 25.6s   ->  xlsx + csv
```
That screen's date columns are `fromYmd` / `toYmd` - a third naming, after
`paramEndDate` and `paramToDate`, and the word-based matching handled it
without being told.

### 24.2 There was no record of what happened
**Symptom** Asked for: *"a complete detailed log so you can know what
happened with it in the problems and bugs."* Every diagnosis in this project
so far has depended on a screenshot taken in time or a console window that
had not yet been closed.
**Fix** `gmes_log.py` mirrors stdout into `logs/gmes_<date>.log`, appended,
with a timestamp on every line: the command line and Python version, every
question and the answer given, every numbered step with its duration, every
warning, and the **full traceback** of anything that fails - the console
still gets one readable sentence.

A tee rather than log calls beside every print, because a log kept in step
by hand goes stale the first time someone forgets a line. Colour codes are
stripped on the way to the file. Nothing sensitive reaches it: the password
is never printed (CLAUDE.md 2.2) and dataset dumps never go to stdout (2.3).
`logs/` is git-ignored - a filter value can be a production order.

One trap in writing it: `_Tee.isatty()` must report the **console's** state,
not the file's, or wrapping stdout silently turns off every colour in
`gmes_ui`.
---

# Phase 25 — the worst kind of bug, found by the user trying to break it

### 25.1 It said VD, the screen had MOBILE, and the file was labelled VD
**Symptom** The user ticked **MOBILE** in the org tree by hand, then let the
tool replay `M4151UM00`, which remembers `division=VD`. The tool reported

```
  ✓  4  Tick the division ... VD
  COMPLETE  ·  288 rows
```

and delivered `Work Calendar_20260910_122310.xlsx`. The screen at that moment
read **`Org MOBILE | Prod All | Proc All`**. Those 288 rows were MOBILE's, in
a file the log called VD. No error, anywhere.

**Cause** Two faults compounding.

1. **A screen can hold the same category tree several times.** Work Calendar
   has **three** copies of `OrgCategory_GDS.dsCatCommonTreeNodeDVO`, one per
   panel tab. `_dataset()` returns whichever the form walk reaches first, so
   the write went into one copy while the visible tree — the one the user had
   clicked — kept MOBILE. Measured live: three instances, two holding VD and
   one empty.
2. **Nothing checked.** `select_org()` reported success on the strength of
   its own write returning without error — exactly what rule 3.5 forbids.

**Fix**
- `tick_org()` writes **every** instance of the tree, not the first. They are
  the same logical tree, so this is both safe and the only way to be certain
  the visible one was included. The exclusive clear reaches all of them too:
  the round trip unticked 20 entries across 3 copies, where the old code
  cleared inside one.
- `org_selection()` reads the screen's OWN summary label
  (`staCategory` / `staCategoryOri` → `"Org VD l Prod All l Proc All"`), and
  `select_org()` polls it until it agrees with what was asked for. A
  disagreement now **raises** and refuses to query.

Confirmed the label tracks a dataset write, before trusting it as the check:
```
start                     : Org VD l Prod All l Proc All
write MOBILE (3 copies)   -> t+0.0s  Org MOBILE l Prod All l Proc All
write VD back             -> Org VD l Prod All l Proc All
```

**Verified against the exact trick.** MOBILE ticked by hand, then replay
P1112UM00 (which remembers VD):
```
  ✓  4  Tick the division
        VD  (screen confirms VD)  (unticked 1: MOBILE)
  ✓  6  Press Inquiry and wait for the answer ··· 800 rows in 16.7s
  COMPLETE  ·  800 rows
```
800 is VD's established count on that screen and date; MOBILE's was 288.

**Lesson** The most valuable test of this project so far was a user
deliberately putting the screen into a state the tool did not expect. Every
"verify the outcome" rule in CLAUDE.md was written for this shape of failure,
and `select_org` was the one step that had never had one — because a dataset
write "obviously" works.

### 25.2 An empty run erased the memory
**Symptom** `P1111UM00` was recorded with VD and a date range, then run once
with everything blank, and its remembered values came back empty — so the
screen list showed it with nothing and the next replay asked cold.
**Cause** `save()` replaced the `values` block wholesale.
**Fix** `_merge_values()` keeps the last **non-empty** answer per field. A
screen legitimately run with no division (Work Calendar needs none) can no
longer erase what another run proved.

### 25.3 The division list was truncated
`...and 14 more` — on the one question where the list IS the set of valid
answers. You cannot choose a division you were not shown, and CLAUDE.md 4.5
already forbids a cap that hides part of the answer. All of them are printed
now, with the count.

### 25.4 A message that was simply untrue
A screen with genuinely nothing to remember was told *"this screen was
recorded before the values were kept"*. It now says *"nothing is remembered
for this screen yet"*.

### 25.5 On CMD versus PowerShell
Asked whether the console was to blame. It is not: `cmd.exe` renders the
colours and box-drawing correctly, `gmes_ui` detects and degrades where a
console cannot, and none of the faults above touched presentation. No change
made.

---

# Phase 26 — remember what was USED, not what was typed

### 26.1 Replay still asked for the division
**Symptom** *"It still asks about the division for replay."* `P1111UM00`
showed `nothing is remembered for this screen yet`, while the three other
screens in the same list showed their divisions.
**Cause** Phase 25.2 stopped an empty run from erasing a memory, but the
damage to that one profile was already written:
`values: {division:'', from:'', to:'', sets:{}}` and
`command: '--division None --from None --to None'`. It was recorded with VD
at 09:59, then run blank at 12:02 - before the merge existed.
**The deeper fault** The memory stored what the *user typed*. A run that
names no division still queries whichever one is ticked, so "" was never the
truth about that run - it was just the absence of an answer.
**Fix** `run_screen()` reads `org_selection()` immediately before Inquiry and
stores **that** as the division used. So:
- naming VD stores `VD`;
- naming nothing stores whatever the screen actually had in effect, and says
  so: `division : none asked for; the screen has VD in effect`;
- and the spelling is fixed for free - a division typed `vd` is stored as the
  tree's own `VD` (P1112UM00 had `division=vd` sitting in it).

### 26.2 A crash this exposed: `.get(key, {})` returns None
**Symptom** `[✗] STOPPED: 'NoneType' object has no attribute 'get'` on
replaying `P1111UM00`, after three steps.
**Cause** `profile.get("division", {}).get("dataset")`. The default applies
only when the key is ABSENT; `P1111UM00` has `"division": null`, so the
`.get` returned `None` and the chained call died. Written twice more in the
same shape (`grid`, and one in `gmes_profile`).
**Fix** `(profile.get("division") or {}).get(...)` everywhere, and a check
that none of the pattern remains.
**Lesson** The profile format grew a field that can legitimately be null, and
three call sites had assumed a dict default covers that. It does not.

### 26.3 Two confirmations for one decision
`Run it?` was immediately followed by `Press Enter to start`. The second gate
is skipped when the first one was the confirmation - which is the shortest
and most common path.

**Verified** - a full replay in three keypresses, with no division question:
```
  2. Which screen?  -> Enter (P1111UM00, the most recent)
  3. Run it?        -> Enter
  ✓  4  Tick the division ········ VD  (screen confirms VD)
  ✓  6  Press Inquiry ············ 213 rows
  COMPLETE  ·  213 rows   ->  xlsx + csv
```

---

# Phase 27 — a shortcut to a different screen, hiding inside a Grid

### 27.1 Quick View affects the process and was never shown at RECORD time
**Symptom** The user, opening `P1114WM00` (PO Batch Monitoring) for the first
time: *"we have a new case here this is affecting the process but not show
when record"* — pointing at a **Quick View** panel on the left, listing "PO
Batch Monitoring" and "PO I/F Monitoring", which the RECORD summary said
nothing about.

**Cause, found with the read-only inspection tools rather than guessed:**
`gmes_find.py "PO I/F Monitoring"` located the panel as a Nexacro **Grid**
(`grdWidgetList`, class `Grid grd_LF_QuickView`) bound to a dataset named
`dsWidget`, living on `WidgetFilter.xfdl.js` — a shell form present on every
screen (confirmed present on both `P1112WF00` windows too). Reading that
dataset with `gmes_data.py read winPPM0221_2_130 dsWidget` showed it is not a
filter at all: it is a filtered slice of the **same menu catalogue** behind
the top search box (gotcha #21) —

```
menuId PPM0693  sysScreenId P1114WM00  "PO Batch Monitoring"   (current)
menuId PPM0694  sysScreenId P1114WM01  "PO I/F Monitoring"     (a DIFFERENT screen)
```

`JS_LEFT_OPTIONS`, which drives the "Left-panel options" section, only
recognises elements classed `Button` or `CheckBox`. A Grid, its rows and its
cells all fail that test, so the whole mechanism was invisible — not
mis-classified, just never looked at.

**What the blast radius actually is** `_findForms(screenCode)` matches by the
loaded xfdl's own file name, so if this were ever clicked mid-run the next
`discover()` would stop finding forms for the requested code and raise "no
forms for this screen code" — a loud failure, not a silently wrong report.
The exposure today is opacity (a first-class thing the screen has, on par
with Divisions, that RECORD never showed), not silent data corruption.

**Fix** `gmes_core.discover()` now finds this shape directly — a dataset
carrying `sysScreenId` + `menuId` + `quickViewId` — inside the work window
being examined, and reports each entry with which one is active. RECORD
(`run_gmes_workflow.show_screen_offer()`) prints it as its own **Quick View**
section, states plainly that each entry is a different screen, and names the
sibling's own UI number rather than anything the tool will click. No change
to what a run sets, ticks or clicks.

**Lesson** A discovery mechanism keyed to one visual style (`Button` /
`CheckBox`) is blind to anything built a different way, and Nexacro reuses
the same underlying menu catalogue in more than one visual shape. Matching by
data shape (`sysScreenId`+`menuId`+`quickViewId`), the way org trees are
already found by `commonName`+`_checked`, generalises where a CSS-class test
does not.

### 27.2 A related leak, fixed the same session
**Symptom** The same shell forms are not covered by the `SHELL` exclusion
regex used for the **grids** walk. A live `discover()` on `P1114WM00`
returned `grdWidgetList`/`dsWidget` (area 10,946) and
`grdOrgCategory`/`dsCatCommonTreeNodeDVO` (area 51,459) inside the `grids`
candidate list, alongside the two real result grids (669,333 and 418,036) —
latent noise in the same family as Phase 17.2's shell leak into the *trees*
walk, on a different pair of forms this time. Harmless as measured (both are
far below the 40% rivalry threshold `choose_grid()` uses), but not something
to leave sitting once found.

**First attempt failed silently.** Adding the two file names to `SHELL`
would have also removed `OrgCategory_GDS.xfdl.js` from the *trees* walk —
that form is the org tree's own legitimate home (#40), so filename exclusion
was the wrong tool. The next attempt checked each grid's bound dataset by
looking it up on the grid's *own* form (`h.form[bd]`) and testing its shape —
this passed for `grdOrgCategory` (excluded correctly) but silently failed for
`grdWidgetList`: `h.form['dsWidget']` returned `undefined`, because Nexacro
resolves a `binddataset` reference through the form's ancestor scope at
render time, and the grid's own form does not carry `dsWidget` as an own
property even though it visibly renders from it. The check's `try { } catch
{}` swallowed the lookup returning nothing and just skipped the exclusion —
another instance of the family of bugs in Phase 21.6, where a caught failure
reads as "not applicable" instead of "could not check."

**Fix** Two passes instead of one: first collect every dataset *name* in the
window whose shape matches an org tree or the Quick View widget (walking all
forms, the way `JS_ORG_TREES` and the new `quickViews` detection already do),
then filter grids by checking their bound dataset's *name* against that set —
never by resolving the dataset on the grid's own form. Verified live:
`grdWidgetList` and `grdOrgCategory` are both gone from `grids` on
`P1114WM00`, the two real result grids (`dsGrdDelMainList`, `dsGrdMainList`)
are unchanged, and `quickViews` still reports correctly. 56 offline tests
green throughout.

**Lesson** A property that is not found is not proof that it does not exist —
only that a lookup in one particular place did not find it. Nexacro's own
scope resolution for `binddataset` does more than a plain property access,
and a shape check has to search where the framework would actually look, not
just the most convenient object to hand.

---

# Phase 28 — screen-populated inputs are readable during RECORD

**Symptom** The first-use summary for `P1114WM00` ended with a loose line such
as `...and 1 box(es) the screen fills in code: Category`. It did not identify
the control, show its current value, or explain how a user could set it, and
longer lists were silently shortened to five names.

**Cause** The summary treated visible-but-unbound controls as an overflow note
instead of as part of the screen description. The message was also assembled
as one unwrapped terminal line.

**Fix** The RECORD summary now has an `Other inputs` section. Every discovered
unbound input is listed with its label, control name, current value, and a
`--set "Label=<value>"` example. Values are wrapped to the detected terminal
width by `gmes_ui.wrapped_field()`.

**Lesson** A summary must expose every discovered control needed to reproduce a
screen; a compact cap or an unstructured continuation line hides information
at exactly the moment a new screen is being learned.

---

# Phase 29 — a package silently dropped by an old .gitignore rule

### 29.1 `src/gmes/screens/` never reached `git status` at all
**Symptom** While scaffolding the standalone `gmes.exe` package (see
`ARCHITECTURE.md`), `git add src/` staged every new file under
`src/gmes/` except `src/gmes/screens/__init__.py` — not even as untracked.
No warning, no error; `git status`, `git ls-files` and `git diff --cached`
all simply omitted it, as if it did not exist.
**Cause** `.gitignore` already had `screens/` (no leading slash), added
when `gmes_profile.py` started writing learned screens to a
`screens/` folder at the repo root (recorded run-state, correctly kept out
of git). A `.gitignore` pattern with no `/` in it, other than a possible
trailing one, is **not anchored to the repo root** — it matches a directory
named `screens` at *any* depth. The new package directory `src/gmes/screens/`
collided with it by name alone and was ignored identically to the intended
target.
**Fix** Anchored the existing rule to `/screens/` so it only matches the
repo-root profile-storage folder. `src/gmes/screens/__init__.py` now stages
normally.
**Lesson** The same class of bug as every silent-truncation incident in this
file, just in tooling rather than in G-MES/N-ERP: a name collision produced
"nothing to see here" instead of an error. Any future package/module name
under `src/gmes/` should be checked against `.gitignore`'s *unanchored*
patterns (`logs/`, `Data Hub Folder/` are the other candidates) before
assuming `git add` actually staged it — checking `git status` alone is not
enough when the file in question is exactly the kind `git status` won't
mention.

---

# Phase 30 — forking the browser layer, and a plan that trusted a static read

### 30.1 The migration plan's exclusion list was wrong about `get_page_tab`
**Symptom** The approved standalone-`gmes.exe` migration plan listed
`get_page_tab` alongside `get_webgui_tab`/`score_webgui_tab`/
`is_webgui_candidate` as "N-ERP-only, do not fork" — reasonable from its
default argument (`prefer_url_substring="nerps"`) and from the fact that it
lives in the same "target selection" section of `cdp_common.py` as those
three genuinely SAP-specific functions.
**Cause** The plan was written from reading `cdp_common.py` itself, not
from checking who actually calls each function. `get_page_tab` is
different in kind from its neighbours: it is a generic "pick the top-level
page tab" helper, and grepping every `gmes_*.py` file's `cdp_common` usage
before forking (rather than trusting the plan text) found it directly
imported by `gmes_common.py` (inside `gmes_tab()`) and by `gmes_connect.py`,
and transitively required by `navigate_page()` and `capture_screenshot()`
— both of which G-MES calls constantly (`gmes_login.py`'s `open_gmes()`,
every `screenshot_on_failure()` call site across the codebase).
**Fix** Forked `get_page_tab` into `src/gmes/browser/cdp.py` after all,
with its N-ERP-flavoured default (`"nerps"`) replaced by `None` — every
real G-MES call site already passed `None` explicitly, so this is not a
behaviour change, just dropping a leftover default that never meant
anything to G-MES.
**Lesson** A migration plan written from a static read of the code being
migrated is a starting hypothesis, not ground truth — this project already
knew that about live G-MES/N-ERP behaviour (poll, verify, never assume),
and it turns out to apply just as much to *planning* the refactor of that
code. The instruction to grep real call sites before trusting the plan's
copy list, rather than executing it blindly, is exactly what caught this
before it shipped as a runtime `AttributeError` three phases later.

### 30.2 Other exclusions the same check confirmed
The same grep pass confirmed `profile_dir`, `launch_chrome`,
`connect_with_retry`, `find_visible_leaf_by_text`, `find_visible_by_title`,
`describe_visible_dialog`, and `wait_for_busy_indicator_clear` are never
called by any G-MES file, directly or transitively — the plan was right
about these, and they stayed out of the fork. `wait_for_busy_indicator_clear`
in particular polls an SAP-shell element id (`hiddenLoadingToolbarButton`)
that has no G-MES equivalent; G-MES's own settle-detection is entirely
Nexacro-dataset-based (`poll_inquiry`, Phase 7.3/10.4) and will land in
`screens/verification.py` in a later phase rather than a generic browser
primitive, so no `waits.py` module was created at all in this phase.

### 30.3 `LAST_CHROME_PROCESS` cannot be re-exported through `from X import Y`
**Symptom, caught before it shipped** A first draft of
`src/gmes/browser/__init__.py` re-exported `LAST_CHROME_PROCESS` the same
way as every other name, for a consistent `from gmes.browser import *`
surface.
**Cause** `launch_chrome_with_user_profile()` reassigns
`LAST_CHROME_PROCESS` via `global LAST_CHROME_PROCESS` inside
`chrome.py`. A `from .chrome import LAST_CHROME_PROCESS` binding in
`__init__.py` captures the value at package-import time (`None`) and never
sees the later reassignment — the same staleness trap the *original*
`cdp_common.py` callers always avoided by writing
`cdp_common.LAST_CHROME_PROCESS` (module-attribute access), never
importing the bare name.
**Fix** Left it out of `browser/__init__.py`'s re-exports, with a comment
explaining why; callers read `gmes.browser.chrome.LAST_CHROME_PROCESS`.
Pinned by `tests/unit/test_browser_fork_parity.py`.
**Lesson** A module-level mutable global reassigned via `global` inside its
own module cannot be safely re-exported by `from module import name` one
level up — the importing name and the module's own name diverge silently
the moment the module reassigns it. Access through the module, not the
name.

### 30.4 Verified
`cdp_common.py` and every N-ERP script/test are byte-for-byte untouched.
`src/gmes/browser/{cdp,chrome,interaction,screenshots}.py` hold 19 forked
functions/constants; a new signature-parity test
(`tests/unit/test_browser_fork_parity.py`, 8 tests) pins every forked
function against the original via `inspect.signature`, explicitly
documents the two deliberate signature changes (`get_page_tab`'s default,
`screenshot_on_failure`'s new `directory` parameter and default prefix),
and confirms the exclusion list names real `cdp_common` functions that did
NOT leak into the fork. Full suite green: N-ERP 31/31 (untouched), G-MES
offline 56+2+3+6+14+8 = 89/89.

---

# Open items

| # | Item | Why it matters |
|---|---|---|
| ~~1~~ | ~~The 85 filler rows are an inference~~ | **Closed in Phase 12** — they are LINE SUM / PROC SUM subtotal rows; the grid adds the labels, the dataset stores only the aggregates |
| 2 | **The DRM `.xlsx` has never been opened and checked** | Only the user can — the encryption is opaque to automation. Until then, "the export succeeded" means the file arrived, not that its contents are right |
| 3 | The live NERP test suite has never completed a clean full run | 8 of 17 passed before the session tore down the browser. Not a known code failure, but not proven either |
| 4 | The popup closer would close the Excel export dialog | It runs only during sign-in today. That separation is a convention in the calling code, not something enforced |
| 5 | No scheduled trigger yet | The nightly job runs on demand only |
| ~~8~~ | ~~Sign-in can fail once after a long idle~~ | **Closed in Phase 14.7** — `core.sign_in()` retries once before reporting failure |
| ~~9~~ | ~~`gmes_core.py` has never been run against live G-MES~~ **Closed in Phase 17**  | Its offline tests are green, but every browser-driven part of it — typing into an unbound control, ticking a tree found by shape, closing a tab — is unproven. See Phase 14.9 |
| ~~11~~ | ~~G-MES is refusing this account's sign-in~~ **Closed in Phase 17** — not a defect; sign-in works. The message came from a manual attempt on the ID/password form, a different door from AD SSO | Blocks every live run. Not a code defect: the automation now reports it in seconds instead of hanging, but the account or the stored password still has to be sorted out. Note the login page has two paths — the ID/password form and the AD SSO button — and only the second is the one this tool uses |
| ~~12~~ | ~~The saved G-MES password is refused~~ | **Closed in Phase 20** - it was not refused. A false rejection stopped the run before the password was ever tried |
| 10 | Closing a tab is matched by a `close` class or id inside the tab element | That control has not been seen in a live DOM. If it is named something else, `close()` reports "the tab has no close control" and closes nothing — a safe failure, but a failure |
| 6 | Session-only cookies do not survive into the profile copy | May require an occasional interactive sign-in |
| 7 | Demo step 2 reports 0 popups | Sign-in has already closed them; the trap is real but is evidenced in step 1's output, not in the step that claims it |
| ~~8~~ | ~~Opening a screen by ScreenID~~ | Done in Phase 8 — `gmes_open_screen.py` |
| ~~13~~ | ~~`WidgetFilter.xfdl.js` / `OrgCategory_GDS.xfdl.js` are not in the grid walk's `SHELL` exclusion~~ | **Closed in Phase 27.2** — `grdWidgetList` and `grdOrgCategory` no longer leak into the result-grid candidate list; excluded by dataset shape, not filename, so the org tree's own discovery is untouched |

---

# Recurring lessons

1. **Poll until the thing exists; never sleep a fixed duration.** A tuned
   timeout is wrong in both directions. A loop that exits on detection makes
   a generous cap free.
2. **Wait for the specific control you are about to use**, not a proxy such
   as element counts or `readyState`.
3. **Text matching must filter by visibility, text length and area**, or it
   matches an ancestor and clicks empty space.
4. **Ids that embed an instance number are not addresses.** Use screen
   codes, classes, labels.
5. **A heuristic can invert between screen states.** Test it in each.
6. **The data layer and the screen disagree.** Reconcile before trusting.
7. **Silent failures are the norm here.** Every step verifies its own
   outcome and says what it actually saw.
8. **A cap that truncates silently hides the answer.**
