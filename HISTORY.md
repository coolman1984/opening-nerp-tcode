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

# Open items

| # | Item | Why it matters |
|---|---|---|
| ~~1~~ | ~~The 85 filler rows are an inference~~ | **Closed in Phase 12** — they are LINE SUM / PROC SUM subtotal rows; the grid adds the labels, the dataset stores only the aggregates |
| 2 | **The DRM `.xlsx` has never been opened and checked** | Only the user can — the encryption is opaque to automation. Until then, "the export succeeded" means the file arrived, not that its contents are right |
| 3 | The live NERP test suite has never completed a clean full run | 8 of 17 passed before the session tore down the browser. Not a known code failure, but not proven either |
| 4 | The popup closer would close the Excel export dialog | It runs only during sign-in today. That separation is a convention in the calling code, not something enforced |
| 5 | No scheduled trigger yet | The nightly job runs on demand only |
| 8 | Sign-in can fail once after a long idle | Session expiry produced no SSO window on the first attempt; a retry worked. The runner should retry sign-in before failing a batch |
| 6 | Session-only cookies do not survive into the profile copy | May require an occasional interactive sign-in |
| 7 | Demo step 2 reports 0 popups | Sign-in has already closed them; the trap is real but is evidenced in step 1's output, not in the step that claims it |
| ~~8~~ | ~~Opening a screen by ScreenID~~ | Done in Phase 8 — `gmes_open_screen.py` |

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
