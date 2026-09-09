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

# Open items

| # | Item | Why it matters |
|---|---|---|
| 1 | The live NERP test suite has never completed a clean full run | 8 of 17 passed before the session tore down the browser |
| 2 | The popup closer would close the Excel dialog | It runs only during login today; that separation is a convention, not enforced |
| 3 | The user has not yet confirmed the DRM `.xlsx` opens correctly | Only they can — the DRM is opaque to automation |
| 4 | No scheduled trigger yet | The job runs on demand only |
| 5 | Opening a screen by ScreenID is not implemented | The job relies on the Production Plan screen already being the default |
| 6 | Session-only cookies do not survive into the profile copy | May require an occasional interactive sign-in |

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
