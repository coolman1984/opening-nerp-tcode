# Project experience: agent field guide

This is the durable onboarding narrative for the opening-nerp-tcode project.
It was distilled from the complete HISTORY.md, CLAUDE.md, SKILL.md,
GMES_SKILL.md, the implementation, the tests, and the project-related
conversation context available to the agents.

The chronological incident record remains HISTORY.md. This file is the
fast mental model: it explains what the project does, why it is shaped this
way, which tempting approaches already failed, what was actually verified,
and what remains open. Read the history when the exact incident matters.

The project automates live Samsung enterprise systems on Windows through
Chrome DevTools Protocol (CDP). It is designed around a difficult fact:
these systems often accept an action and produce no error even when nothing
useful happened.

---

## 1. The one-minute understanding

| System | Technology | Supported work |
|---|---|---|
| N-ERP | SAP GUI for HTML inside a Fiori shell | Open a T-code, fill its selection screen, press Execute, export the list |
| G-MES | Nexacro manufacturing execution system | Sign in, open any reachable screen, discover/set controls, run read-only Inquiry, verify, export |

The safe mental model is:

1. Observe the exact control or state that will be used.
2. Use the event/data mechanism the application actually listens to.
3. Read back the result and prove it is the requested result.
4. Stop at the first unknown state and preserve evidence.

The normal operations are read-only. Opening screens, setting filters, running
Inquiry, reading datasets, and exporting are in scope. Saving, submitting,
approving, deleting, or changing business data requires explicit user
confirmation for each action.

---

## 2. Non-negotiable rules

CLAUDE.md is the authoritative policy and must be read before changing
anything. The following rules summarize the decisions that have repeatedly
prevented production mistakes.

### Safety and data

- Never delete or modify the user’s real Chrome profile. N-ERP’s disposable
  launch path may remove only its own throwaway profile. G-MES runs against a
  persistent copy and never deletes the real profile.
- Store credentials only through the Windows DPAPI-backed store used by
  gmes_credentials.py. Never put passwords in source, arguments, environment
  variables, output, logs, screenshots, commits, or documentation.
- Never print or commit G-MES session tokens. The integrated-search dataset can
  contain tokenId and refreshTokenId JWTs. Read only the needed columns.
- Never commit production exports or screenshots. Existing data/output paths
  are ignored; add any new output location to .gitignore in the same change.
- Never kill the user’s browser. taskkill against all chrome.exe closes every
  user window. G-MES closes its own automation browser through CDP.

### Engineering

- Any behavior change requires a HISTORY.md entry in the same commit, using
  Symptom / Cause / Fix / Lesson. Durable system discoveries also belong in
  the numbered gotchas in SKILL.md or GMES_SKILL.md.
- Never sleep a fixed duration. Poll the condition that matters with a
  generous cap; a sleep is acceptable only as the interval inside a poll.
- Wait for the named control that will be used, not readyState, an element
  count, or the mere existence of a target.
- Generated IDs are not addresses. Use stable labels, classes, dataset names,
  screen codes, breadcrumb codes, or fixed shell IDs only.
- Verify every transition: requested screen, active screen, applied filters,
  organization selection, result dataset, result date/value, file path, and
  file size.
- Prefer the application data layer over visible grid scraping.
- Address CDP through 127.0.0.1, never localhost, and rewrite websocket URLs
  the same way.
- Save a failure screenshot from the page target, never from an iframe target.
- Stop at the first unrecognized dialog/state. Do not guess the next action.

### Change procedure

1. Read CLAUDE.md, this guide, and the relevant HISTORY.md phase.
2. Read the relevant numbered gotchas.
3. Inspect the live page/data shape with the read-only tools before writing a
   selector.
4. Reuse shared helpers rather than creating a second wait/target/export path.
5. Add an offline regression test or mock trap when possible.
6. Add the history entry in the same change.
7. Verify the real outcome and report uncertainty honestly.

---

## 3. Browser and CDP mental model

cdp_common.py owns Chrome discovery/launch, proxy bypass, CDP target lookup,
websocket connections, JavaScript evaluation, real mouse/key dispatch,
polling, tab selection, and screenshots.

There are two network paths:

1. Python to Chrome’s local CDP endpoint. Corporate proxy variables can
   intercept it, so imports set NO_PROXY/no_proxy and calls use 127.0.0.1.
2. Chrome to the enterprise pages. Real portals use the corporate proxy.
   The mock browser alone uses no-proxy-server; do not apply that to
   production.

The target list changes during navigation:

- N-ERP Fiori is a page target.
- SAP WebGUI is a separate cross-origin iframe target.
- G-MES can have the page, ADFS/SSO windows, child popups, and many work tabs.
- Stale and duplicate targets accumulate.

An idle websocket can become stale while a page navigates. Close it during
navigation and attach afresh for each poll. If a target is replaced,
re-resolve it rather than retrying the dead socket.

DOM element.click() is not a reliable enterprise action. Use a visible leaf,
obtain its current bounding rectangle, dispatch mouseMoved/mousePressed/
mouseReleased, then poll for the resulting state. A non-zero rectangle can
still be off-screen; menus have appeared at y=-99984 before repositioning.

---

## 4. N-ERP pipeline and hard-won lessons

### Pipeline

1. search_tcode.py opens the portal, types the requested T-code into Search
   Program, clicks Go, waits for the SAP screen, and verifies that the
   screen belongs to that T-code.
2. execute_filters.py finds inputs by stable title labels, writes values,
   finds the real Execute control, dispatches a mouse click, and waits for
   the result state.
3. export_to_excel.py tries transaction-specific export triggers,
   recognizes the dialog by content, fills a generated filename, confirms
   the right flow, and waits for the download confirmation.

run_nerp_workflow.py launches the clean CDP browser and orchestrates all
three. NERP_Workflow.bat is the double-click entry point.

Typical commands:

~~~text
python run_nerp_workflow.py MB52 "Material Number=SM-A137FLBHMEB" "Plant=P703"
python run_nerp_workflow.py MB52 "Plant=P703" --no-export
python search_tcode.py MB51
python execute_filters.py "Plant=P703"
python export_to_excel.py MB51
~~~

### Failure lessons

| Symptom | Cause | Fix and lesson |
|---|---|---|
| Execute was found as the whole screen and the run waited forever | textContent is inherited by ancestors; a large container matched before the button | Prefer the precise F8 title; otherwise require visible, short text and choose the smallest box |
| Export attached to a stale WebGUI frame | The stale frame had an input while the live result list had none; “most inputs” inverted after Execute | Reject the AppDynamics decoy and score candidates by rendered content |
| Navigation raised ConnectionResetError | chrome://newtab is a privileged WebUI target and navigation can tear down CDP | Launch at about:blank; treat navigate acknowledgement as optional and poll |
| The last shortcut was blamed for an unknown dialog | The loop kept firing shortcuts into a modal | Stop at the first unknown dialog and print its text |
| Synthetic click did nothing | SAP/Fiori controls listen for mouse events | Dispatch real mouse events at the current rectangle |
| A field ID stopped working | SAP dynpro IDs regenerate | Match the title label, not the ID |
| contentDocument could not reach the report | WebGUI is cross-origin and a separate CDP target | Connect directly to the iframe target |
| Screenshot failed on the WebGUI target | Screenshots are top-level-only | Capture on the surrounding page |
| A dialog was absent after two seconds | Server/UI timing varies | Poll every dialog and follow-up button |
| OK stayed focused while the dialog remained | A click can be focus-only | Poll for confirmation and re-click once during the window |
| Escape navigated away from the result | Escape is bound like Back/F3 | Never use Escape as generic cleanup |
| An unrelated old report reopened after restart | Session restore reused a stale profile/tab | Delete only the disposable N-ERP profile and verify the T-code |
| A large export waited unpredictably | Server preparation depends on data size | Use a generous cap and poll the actual dialog/status |
| A fixed 30-second load was too short or wasteful | Network/render time varies | Poll for the named control |

### Export flows

SAP binds shortcuts per transaction. The exporter tries Shift+F4,
Ctrl+Shift+F7, Shift+F7, Ctrl+Shift+F9, then the toolbar Export icon followed
by Spreadsheet.

- Flow A: Export As → Export to... → Enter file name to save → OK.
- Flow B: direct Enter file name to save, often with a default .XLSX name.
- Flow C: Save list in file... → Text with Tabs → icon-only Continue →
  filename dialog. Change the Save as dropdown from Text Files to Spreadsheet
  Files (*.xlsx), or SAP silently creates text instead of a workbook.

If no trigger creates a recognized dialog, the current view may be a
single-record page rather than a list. Preserve the screenshot; do not invent
another shortcut.

### N-ERP evidence

tests/mock_nerp_server.py deliberately reproduces delayed controls, real-mouse
behavior, an encoded AppDynamics decoy, stale frames, slow dialogs, and
off-screen dropdowns. tests/test_unit.py covers decision logic, and
tests/test_live_chrome.py drives the mock with real Chrome/CDP on a dedicated
port/profile. The history records that a full clean live run was once
interrupted by browser teardown; this is an infrastructure verification gap,
not proof of a code failure.

---

## 5. G-MES application model

G-MES is Nexacro, not SAP. It has real DOM controls with meaningful IDs, but
the complete result data is in Nexacro JavaScript datasets rather than the
visible grid.

The stable address is the screen code printed in the breadcrumb, for example
P1112UM00 or P1112WM00. Work-window IDs contain a changing instance suffix.
Only shell IDs are stable:

~~~text
mainframe.vFrameSet1.vFrameSet2.topFrame
mainframe.vFrameSet1.vFrameSet2.loginFrame
mainframe.vFrameSet1.vFrameSet2.mdiFrame
~~~

The top search box opens screen codes. The client-side gdsMenuList catalogue
has 1177 rows, including 809 reachable screens, with menuId, sysScreenId,
English/Korean titles, and screenSn breadcrumb ancestry. gdsMenuList_ is the
wrong catalogue: Korean-only titles and a different menu-ID series made
English searches silently empty.

gmes_core.py is the shared generic engine. It discovers a screen, applies
options, organization, dates, and filters, activates the tab, runs Inquiry,
waits for the screen’s actual dataset, verifies optional values, exports,
writes CSV, and remembers only after the complete run succeeds.

---

## 6. G-MES launch and sign-in lessons

### Chrome profile restriction

Chrome 136 and later silently ignore remote-debugging-port when launched
against the default profile. clone_user_profile() copies the real profile to
a persistent CDP Profile (historically about 928 MB became 338 MB after
cache exclusion). Extensions and saved logins survive; session-only cookies
may not. The copy is never deleted.

refresh-profile explicitly re-copies the real profile and warns that it
destroys the session currently stored in the copy. Chrome must be closed
before refreshing because files may be locked.

The user’s own Chrome can remain open. The automation uses a different
profile; an experiment with 30 user Chrome processes showed that the copy
can start normally. Only a stale process holding the copy should block launch.

### Authentication

G-MES has a direct ID/password form and an AD SSO button. The automation uses
AD SSO first and DPAPI credentials if an ADFS window appears. A surviving
session cookie can sign in immediately without any ADFS window, so the wait
must race:

1. signed-in user-name button;
2. ADFS window;
3. a complete timeout with neither.

direct_login() must write through the Nexacro component; setting only an
inner HTML input value looks correct but submits nothing. Read back only the
user ID and a boolean indicating that a password is set.

A stale Auth bad credentials message is not authoritative. It can be left by
an earlier manual attempt while ADFS is still about to open. Signed-in state
wins; an SSO window is completed; only a full wait with neither outcome makes
the message a real failure.

Retry only transient FAILED states (for example session expiry). A terminal
REJECTED credential failure must not be retried toward account lockout.

If a page load replaces the target socket three times, reconnect and say that
it is reconnecting. Never use except Exception: pass to turn a dead socket
into a four-minute apparent hang.

### Notice popups

The Notice popup is modal and silently swallows clicks behind it. It can
arrive seconds after sign-in and more than one may queue. Close by the
Nexacro child-window shape:

~~~text
.TitleBarControl.titlebarChildFrame .closebutton
~~~

Do not match the Korean title or a one-off ID. The Excel dialog is also a
child window, so the generic closer must run only during sign-in. On an
already-signed-in session, sweep once; do not pay the 45-second arrival wait.
Stop if repeated clicks fail to reduce the popup count.

### Blank page and localStorage quota

G-MES writes a timestamped copy of its Nexacro engine into localStorage on
each load and never removes old copies. At about 102 entries and 5 MB,
bootstrap throws QuotaExceededError:

~~~text
ready: complete   nexacro: True   app: False   divs: 3   text: ''
~~~

This is a failed bootstrap, not a slow page or HTTP outage; reload alone does
not help. prune_nexacro_cache() keeps the newest engine and removes stale
copies. One observed cleanup removed 51 copies, freed about 4.94 MB, and the
app rebuilt in under four seconds. After about 20 seconds without a named
login/session control, inspect app_is_built(), report storage, prune once,
and reload.

---

## 7. G-MES discovery and data-layer lessons

### Nexacro object walk

Child frames live in _frames, a numeric ObjectArray, not a useful frames
property. A work screen is nested in Div components and their form objects,
not a frame itself. A frame-only walk finds the shell and falsely reports no
screen.

An earlier cap of 60 forms hid a target in an application with 206 forms.
Never silently truncate a catalogue or result; a visible cap must be
generous and report when reached.

form.binds maps a control to a dataset column, such as:

~~~text
divBasic.form.divCal.form.mskDateFrom -> dsFilterDVO.paramFromDate
~~~

It is the foundation of generic filter discovery, but:

- bound Statics are outputs, not filters;
- shell forms contribute unrelated bindings;
- some screens bind no filters because code drives them;
- result grids are identified through binddataset.

Unbound visible inputs still matter and can be set by real key events.

### Screen search/opening

The suggestion list is produced by onkeyup; set_value() alone does not
search. Focus the box and send per-character keyDown/char/keyUp.

The same suggestion title appears in a detail panel and a result grid.
Text matching can hit the detail panel, which does nothing. Read
dsSearchResult, choose by data, and click the grid row:

~~~text
grdResult.body.gridrow_<n>.cell_<n>_0
~~~

Opening is not activation. Background screens accept dataset writes while
Inquiry lands on the visible screen. Activate the tab
mdiFrame.form.divTab.form.TAB_<winId> and confirm the window is visible.

### Result grids and shell leaks

The grid renders only visible rows; always read the dataset for complete data.
A screen can have several grids. The largest visible grid is a fallback, but a
second grid within 40 percent of its area is reported as ambiguous and the
caller should use --grid. An unmatched explicit preference fails with the
candidate list.

Export creates a temporary __EXCEL__ clone; it must not enter the screen
fingerprint or result-grid candidates.

Quick View is a Grid, not a Button/CheckBox option. dsWidget rows contain
menuId, sysScreenId, and quickViewId. They represent other screens, not
filters. RECORD reports the active entry and sibling screen codes but does
not click them.

WidgetFilter.xfdl.js and OrgCategory_GDS.xfdl.js can leak shell grids into
result candidates. Excluding the entire form would hide a legitimate Org
tree. The correct fix collects org-tree and Quick View dataset names across
all forms, then excludes grids bound to those names. Nexacro can resolve
binddataset through ancestor scope, so a grid-local property lookup is not
enough.

---

## 8. Filters, organization, dates, and options

### Organization

Missing Division produces “Select Search Criteria” and an empty grid with no
hard error. Trees are discovered by shape: commonName plus _checked. Org,
Prod, Fac, and Proc each can have their own tree. Choose by the tree that
contains the requested name, not by first/biggest.

The same logical tree can appear several times on one screen. Work Calendar
had three copies. tick_org() writes all copies, clears unrequested ticks when
exclusive=True, and select_org() verifies the screen’s summary label
staCategory/staCategoryOri. A dataset assignment returning without error is
not verification.

Organization matching is case-insensitive. Save/report the canonical spelling
from the tree, not the caller’s spelling.

### Dates

Dates are usually bound dataset values, not calendar-widget actions. Set the
dataset and read back the control. For unbound fields, click, Ctrl+A/Delete,
send real key events, Tab to commit, and read both focused and unfocused forms.

Names vary: paramFromDate, paramEndDate, paramToDate, planYmd, stdYm,
fromYmd, toYmd, and paramPeriod1 are all real examples. Recognize whole
words date, ymd, ym, dt, period, or day, or masked/calendar control types.
Do not substring-match: paramVendorCode contains “end” but is not an end date.

Fit the value to the field width: YYYYMMDD, YYYYMM, or YYYY as already held.
normalise_date() accepts YYYYMMDD, YYYY-MM-DD, and YYYY/MM/DD, validates a
real calendar date, and rejects partial/nonexistent dates.

If a screen has one date field and two different endpoints are requested,
stop. If several single date fields have no clear pair, set only the proven
target and warn. Do not guess.

### Left-panel options

These query decisions are not ordinary filters:

| Option family | Meaning |
|---|---|
| Org / Prod / Fac / Proc | Category tree source |
| STD / PLANT | Organization attribute |
| Including Past Org. | Include closed organizations |
| Plan Date / Create Date / similar | Meaning of the date period |
| General / Compare / OI | Search mode |
| Quick View | Different screen/result path |

Classes _Sel, Category_Sel, and ToggleSearchV2 mean selected; _Dis and
_Default mean unselected. left_options() lists them and set_option() clicks
by label then verifies the class.

Apply options before organization and dates because rebuilding the left panel
can discard earlier writes. Learned options are reapplied on replay unless
the current run explicitly names its own.

---

## 9. Inquiry, verification, exports, and row counts

### Inquiry wait

Inquiry clears the result dataset immediately, then refills it after the
server responds. Stable zero is not finished. poll_inquiry() watches the
dataset discovered for the current screen, requires a changing count, then
settling above zero. A long grace period is used before calling an all-zero
query genuinely empty.

A previous screen can leave a same-named dataset populated. Watching a
hardcoded dsMasterProdPlan once caused a log to claim 875 rows while the
second report actually returned 17; the file was right but the log was wrong.
That is more dangerous than a visible failure. The wait must be parameterized
by the current screen’s discovered dataset.

### Verification

--verify COLUMN[=VALUE] is strict and blocks export on mismatch. Without it,
date-like result columns are reported with samples, not treated as proof.
Value shape alone is insufficient: prodTime, model codes, and week numbers
can look like six/eight-digit dates. The column must also be named like a
date.

### Excel and CSV

The G-MES Excel icon opens PopupExcelExport and requires OK. Download behavior
must be configured on the same CDP connection that performs the click; a
separate connection can leave the file in Downloads.

The workbook carries the NASCA DRM marker and is readable by Excel with the
Samsung DRM client, but not by openpyxl, pandas, or ZIP readers. check_download()
therefore proves existence and a non-trivial size, while CSV is the content
evidence.

Production Plan has subtotal rows with empty poNo/masterLine. Observed:
875 dataset rows minus 85 blank-key rows equals the grid’s 790 total. The
grid adds LINE SUM and PROC SUM labels at render time. The screen-specific
nightly exporter may drop empty poNo rows. The generic exporter must not
assume that key on an unknown screen; it drops only completely empty rows and
reports both counts.

---

## 10. Profile memory and RECORD/REPLAY

gmes_profile.py remembers stable references only after a fully successful run:
open, apply, verify, query, export, and file check.

Safe references:

- screen code, title, menu ID;
- dataset/column references for dates;
- organization tree dataset and entry;
- result-grid dataset;
- learned option labels;
- last values actually used;
- command summary.

Never remember coordinates, window IDs, dataset contents, passwords, or
tokens. Coordinates are valid only for the evaluate/click moment; IDs
renumber; datasets can contain JWTs.

Fingerprint exactly what the profile relies on: bound dataset.column
identities and result-grid dataset names as sets. Do not fingerprint volatile
visibility, arbitrary control IDs, or the __EXCEL__ clone. If a referenced
control/grid vanishes or the screen shape changes, explain the drift and
rediscover; never repair a profile silently. --relearn explicitly discards it.

Remember what was used, not only what was typed. If no division was supplied,
read the organization summary immediately before Inquiry and save the
organization actually in effect. Merge non-empty new values with old so an
empty run cannot erase proven memory. Older profiles can recover values from
their proved.command string. Null profile fields require
(profile.get("field") or {}) before chaining get().

REPLAY with remembered values should show the remembered settings and ask one
Run it? confirmation. It should not re-ask every known field. A failed or
invalid run returns to the session loop. Closed stdin is different from a
blank answer; InputClosed prevents infinite re-asking.

---

## 11. User-facing G-MES workflow

~~~text
python gmes_report.py find "production plan"
python gmes_report.py describe P1112UM00
python gmes_report.py run P1112UM00 --division VD --days-back 1
python gmes_report.py run P1112UM00 --date 20260908 --verify planYmd
python gmes_report.py run P1112UM00 --set "Production Order=<value>"
python gmes_report.py run P1112UM00 --option PLANT --option "Create Date"
python gmes_report.py run P1112UM00 --dry-run
python gmes_report.py run P1112UM00 P1111UM00 --division VD --days-back 1
python gmes_report.py run P1112UM00 --manifest run.json
python gmes_report.py run P1112UM00 --close-tabs
~~~

The interactive front end (run_gmes_workflow.py or GMES_Workflow.bat):

1. asks for RECORD or REPLAY;
2. validates the screen from the local 809-screen catalogue;
3. in RECORD, opens and activates the screen before asking about controls;
4. shows result grid, date fields, other inputs, divisions, options, and
   Quick View entries actually present;
5. asks only questions supported by that screen;
6. applies options, organization, dates, and named filters in that order;
7. runs and verifies Inquiry;
8. exports and saves memory only after success.

The narrator is a display layer, not a decision layer. Unknown log keys are
printed raw. Long sign-in work remains visible; captured output is printed on
failure. gmes_log.py mirrors stdout to ignored timestamped logs with command,
Python version, questions, answers, durations, warnings, and tracebacks,
while excluding passwords and raw datasets.

---

## 12. Module map

| Module | Responsibility |
|---|---|
| cdp_common.py | Shared CDP, Chrome/profile launch, proxy bypass, input events, target selection, waits, screenshots |
| search_tcode.py | N-ERP portal search and T-code verification |
| execute_filters.py | N-ERP fields, Execute, busy wait |
| export_to_excel.py | N-ERP trigger/dialog flows |
| run_nerp_workflow.py | N-ERP orchestration and parsing |
| gmes_credentials.py | DPAPI credential storage |
| gmes_common.py | G-MES target, readiness, cache pruning, controls, login state, popups |
| gmes_login.py | AD SSO/direct login, retry classification, status |
| gmes_data.py | Nexacro forms/datasets and safe CSV |
| gmes_open_screen.py | Catalogue search, key events, suggestion row, tab activation |
| gmes_core.py | Generic screen discovery, options, trees, dates, filters, Inquiry, verification, export, profiles |
| gmes_profile.py | Stable references, fingerprints, drift, remembered values |
| gmes_report.py | Generic find/describe/run CLI |
| gmes_daily_prodplan.py | Screen-specific nightly Production Plan wrapper and subtotal cleanup |
| run_gmes_workflow.py | Guided RECORD/REPLAY questions and narration |
| gmes_ui.py | Terminal presentation only |
| gmes_log.py | Timestamped stdout/traceback log |
| inspection/probe scripts | Read-only reconnaissance and diagnosis |

The nightly job and generic runner must share core mechanics. Duplicated
inquiry waits, target selection, or export logic have repeatedly drifted and
caused wrong counts.

---

## 13. Chronological experience

This timeline preserves the important experience of every phase in
HISTORY.md. The exact incident evidence remains there.

### Phase 0: original N-ERP

The original skill knew proxy bypass, real mouse input, cross-origin WebGUI
targets, stable labels, and polling, but did not yet guarantee them.

### Phase 1: audit

The project initially could not run because the active Python lacked
websocket-client; docs pointed at another user’s absolute path; docs
contradicted the newer CLI parser; and configuration/chrome discovery was
duplicated. The response was requirements.txt, an actionable import error,
portable docs, and one cdp_common source of truth.

### Phase 2: N-ERP rebuild

The Execute ancestor-match bug, stale-frame heuristic, navigation reset, and
unknown-dialog continuation were fixed. Shared message IDs, named JS errors,
broad connection retries, screenshots, and real T-code verification followed.
The central lesson: a heuristic must be tested in every screen state.

### Phase 3: test harness

The mock portal proved that synthetic click is ignored while dispatched mouse
events work, and that the live frame wins after Execute even with zero inputs.
It also separated Python proxy behavior from Chrome page-request behavior.

### Phase 4: G-MES connection

Chrome’s profile restriction forced the persistent profile-copy design.
Reconnaissance established real DOM controls and no canvas.

### Phase 5: unattended login

DPAPI credentials, a non-interactive Tk prompt, named readiness controls,
delayed Notice watching, class-based popup close, and user-name signed-in
detection were added. The absence of a login button is not sign-in evidence.

### Phase 6: Nexacro data

Visible grids were proven incomplete. Correct _frames/nested-Div traversal
reached datasets. The 60-form cap was removed. Window IDs and breadcrumb
screen codes were separated.

### Phase 7: nightly export

Production Plan taught the project that Division is mandatory, dates are
bound dataset values, Inquiry clears the dataset before refill, Excel is a
dialog, download behavior is connection-scoped, workbooks are NASCA DRM, and
85 blank-key rows are LINE SUM/PROC SUM subtotals. CSV became the readable
evidence.

### Phase 8: any screen

The real gdsMenuList catalogue and ScreenID search were found. Search needed
key events; the suggestion grid row—not the detail panel—had to be clicked;
the active tab had to be confirmed. Session-restored sign-in and clear
connection-refused errors were handled. Two fixes were once shipped without
history entries; that process failure is itself recorded.

### Phase 9: demo

Fourteen read-only steps proved directory, screen activation, date writes,
organization selection, dataset/grid reconciliation, and changing IDs. The
popup demo step may report zero after sign-in already closed the notices.

### Phase 10: generic runner

form.binds made screens self-describing. Bound Statics/shell forms were
excluded, unbound controls were surfaced, dates became vocabulary-driven,
grid ambiguity became explicit, and the hardcoded Production Plan inquiry
wait was removed. Screens run sequentially because tabs, export, and popups
are global.

### Phase 11: interactive workflow

Left-panel options became explicit query decisions. The module bar was mapped
but not automated because ScreenID is the stronger universal path. Generic
CSV stopped guessing poNo. Session expiry was separated from rejection.

### Phase 12: real-user defects

Persisted stale filters caused a confident empty result. Case-insensitive
division matching and strict date normalization fixed input hazards. Division
was explained as a different mechanism from --set. Blank rows were confirmed
as subtotal rows.

### Phase 13: performance

The unnecessary popup vigil and IPv6-first localhost resolution made a
signed-in run take about 58.9 seconds. One-time popup sweep and IPv4 CDP
addressing reduced login to about 2.1 seconds and startup to about 0.41
seconds. A bulk edit briefly introduced an undefined empty_grace variable.

### Phase 14: core

Unbound controls became typeable; date detection covered planYmd/stdYm and
widths; grid ambiguity and organization-tree selection were generalized;
screen opening waited for forms; Inquiry waiting was consolidated;
reason-aware sign-in retry, dry-run, verify, manifest, and close-tabs were
added. Offline core tests reached 37.

### Phase 15: memory

Date ranges and profiles were added. Profiles remember stable references, not
coordinates, IDs, values, or tokens. File existence and minimum size became
download verification. Browser-driven replay was explicitly marked
unverified until live evidence existed.

### Phase 16: first live failure

A visible login refusal was ignored for 90 seconds and retried. Outcomes
became OK, transient FAILED, or terminal REJECTED. Credential rejection is
not retried. The apparent account problem later proved to be a different
manual login path.

### Phase 17: live core success

Real dates produced DRM Excel/CSV. Status crashed under a traceback, shell
panels leaked into candidates, and volatile controls made profiles erase
themselves. All were fixed; offline tests reached 49.

### Phase 18: narrated front end

RECORD/REPLAY became visible, remembered tree preferences were consulted,
Production Plan by Model proved a different date naming, date-like outputs
required date-like names, and prompt numbering stopped skipping.

### Phase 19: management demo

Silent sign-in looked hung, Windows Terminal made process handles useless,
and a focus guard protected the user’s foreground window. The demo exposed
that earlier automatic sign-in evidence was session reuse, not proof of a
stored-password login.

### Phase 20: false rejection

A stale login message was treated as authoritative before ADFS appeared.
Signed-in state was restored as primary. refresh-profile was documented as
session-destroying; browser close moved to CDP; SSO target matching improved;
and manual assist was added. A page message is evidence, not a verdict.

### Phase 21: screen-first recording

RECORD now opens the screen before asking questions and shows its actual
filters, inputs, divisions, options, and Quick View. Dead sockets reconnect,
popup loops stop on no progress, and the mode is selected explicitly.

### Phase 22: blank bootstrap

The blank spinner was diagnosed as localStorage quota exhaustion, not a
network failure. Automatic pruning/reload was added. The guard that rejected
any open user Chrome was removed after proving the separate profile works.

### Phase 23: reusable session

One run returns to a session loop. Invalid screen codes are checked against
the 809-screen catalogue before browser work. Profiles began remembering
values. Closed stdin became distinct from a blank answer.

### Phase 24: replay and logs

REPLAY stopped asking for known values and became a one-confirmation path.
Older command strings recover values. Timestamped logs capture questions,
durations, warnings, and tracebacks without secrets.

### Phase 25: deliberate user challenge

A hand-selected MOBILE tree remained while a remembered VD replay wrote only
one of three tree copies. The tool claimed VD and exported MOBILE data. All
copies are now written and the summary label is verified. Empty runs cannot
erase proven memory; the complete division list is shown.

### Phase 26: remember what was used

Memory stores the organization in effect immediately before Inquiry rather
than the caller’s typed string. Null profile values no longer crash replay.
Duplicate confirmations were consolidated.

### Phase 27: Quick View

Quick View was discovered as a data-shaped Grid pointing to other screens and
is now reported during RECORD. Shell grids are excluded by dataset shape.
The grid-local dataset lookup failed for ancestor-scoped dsWidget; collecting
dataset names across all forms fixed it.

### Phase 28: complete RECORD

Unbound controls are listed with label, control name, current value, and a
set example, wrapped to terminal width. A loose overflow line had hidden
exactly the information needed to learn a new screen.

---

## 14. Tests, evidence, and honest limits

Known commands:

~~~text
python tests/test_unit.py
python tests/test_gmes_core.py
python tests/test_gmes_workflow.py
python tests/test_live_chrome.py
~~~

N-ERP has offline decision tests and a real Chrome/mock-portal suite. G-MES
has extensive offline tests for discovery, dates, grids, fingerprints,
profiles, remembered values, and generated JavaScript, plus repeated live
testing of the core and several screens. There is no G-MES mock, so live
browser behavior remains environment-sensitive.

Do not infer live proof from unit tests for a new screen, a new export dialog,
unseen close-tab control, profile refresh/session state, or DRM workbook
contents. The user’s Excel/DRM client is required to inspect workbook
contents.

---

## 15. Open items

1. The DRM xlsx has not been opened by automation and cannot be parsed by
   normal libraries; the user must verify its contents in Excel.
2. A full clean N-ERP live suite has historically been interrupted by browser
   teardown and should be rerun cleanly before claiming complete proof.
3. The popup closer could close an Excel child dialog if called outside the
   sign-in phase; current safety depends on the calling convention.
4. No scheduled trigger exists yet; the nightly job is on demand.
5. G-MES close-tab matching has not been observed for every live screen; safe
   failure reports no matching control instead of guessing.
6. Session-only cookies may require occasional interactive sign-in in the
   profile copy.
7. The demo popup step can report zero after sign-in already closed notices.

Closed items include ScreenID opening, transient sign-in retry, false
credential-rejection diagnosis, live core execution, cache-quota recovery,
stale-tree confirmation, and Quick View discovery.

---

## 16. Conversation continuity

The project-related chats that led to this guide are part of the preserved
context and should be understood as follows.

### Codex CLI update check

The user asked whether Codex CLI had an update. The local command reported:

~~~text
codex-cli 0.153.4
~~~

The official Codex CLI documentation page displayed an older example version
in its sample terminal, so the local installed version was already newer than
that documentation example. The current official CLI guidance describes
interactive repository work, codex exec automation, reviews, session resume,
image context, web search, cloud handoff, MCP, skills/plugins, subagents,
permissions, and shell completion. An example version shown in docs is not a
reliable update check; the local version command is the useful evidence.

### Concurrent Claude CLI agent

The user asked whether a Claude CLI agent was visible. Windows denied access
to the process list through both the CIM and tasklist attempts, so no claim
about a running Claude agent could be made. The correct lesson is to state
the visibility limitation, not infer that no agent exists.

### Read-only project review

The user then asked for a read-only understanding of the project. The review
read the operating rules, README, HOW_TO_USE, both skills, all 2039 lines of
HISTORY.md, the core workflow modules, and test/function maps. No project
logic was changed during that review. At that time the worktree contained
uncommitted changes in HISTORY.md, gmes_ui.py, run_gmes_workflow.py, and a
new tests/test_gmes_workflow.py; those were left untouched because they could
belong to the concurrent Claude work.

This document is the requested durable follow-up to that conversation: it
turns the chronological chat/history knowledge into something a future agent
can read once and carry forward.

### Complete project-chat source inventory

The project’s chat archive is the untracked Doc directory. I read the six
JSONL session logs there and folded their substantive decisions and failures
into this guide. The raw logs are not copied into the markdown because they
contain local paths, screenshots, production examples, and potentially
sensitive browser/session context.

| Chat log | Recorded focus |
|---|---|
| d52aec41-2112-4be0-9038-10b8145aea80.jsonl | The original deep dive: N-ERP rebuild, first G-MES connection, DPAPI sign-in, Notice popups, Production Plan, data-layer discovery, ScreenID navigation, demo, universal runner, and the first generic-core design |
| ee759ace-8676-4e24-b647-64e320a1dfac.jsonl | Follow-up project-deep-dive continuation and unfinished work carried into the next session |
| 285bac09-2dad-4f6f-a962-a2b16a358bf5.jsonl | G-MES core architecture, manual-date V1, dry-run, monitoring, polished visible CLI demo, saved login, RECORD/REPLAY, persistent memory, invalid UI handling, the deliberate MOBILE-vs-VD challenge, bug report, sync, and recovery from a wrong Chrome profile |
| f93f3870-017b-45e0-bf82-86351eb9fcad.jsonl | Discovery of the new Quick View case that the first RECORD summary omitted |
| 1e5cf169-26c3-40cd-8d34-b6b237ff81c6.jsonl | Project overview, final documentation awareness, and request to fix/sync to main |
| c67687dd-819c-4918-9688-2d1cf4fa86a7.jsonl | Questions about seeing or connecting to another CLI agent and the read-only project review |

### User intent and product requirements found in the chats

The user’s long-term request stayed consistent even when individual
debugging requests changed:

- Give the tool a G-MES UI number and only the values the user actually
  cares about, such as Division and a manual From/To range.
- Open the correct screen, inspect that screen, find its own controls, apply
  only the requested values, verify each application, run Inquiry, wait for
  the real answer, download Excel, verify the file, and remember only proven
  screen knowledge.
- Keep V1 deliberately small: manual dates first. Automatic “today”,
  “yesterday”, and date arithmetic belong after the manual workflow is stable.
- Prefer one shared automation philosophy/core with N-ERP-specific and
  G-MES-specific adapters, not two unrelated engines.
- Record a screen once when useful, replay it quickly later, detect drift,
  and fall back to rediscovery instead of blindly replaying old actions.
- Save semantic identities and relationships, not raw coordinates or
  unstable IDs. The user explicitly asked for an always-remembering JSON
  store, but the chats clarified that it must never store credentials,
  tokens, or unsafe volatile state.
- Make the CLI simple, elegant, visible, and understandable to a
  non-technical person. RECORD must show what it discovered; REPLAY must show
  what it remembers and avoid re-asking known values.
- A completed run must return to a choice of RECORD or REPLAY instead of
  closing the session. Invalid UI numbers, filters, divisions, and dates
  must be rejected locally and re-asked with a useful explanation.
- A management demo must be visible side by side with the browser, narrate
  progress, and never appear frozen while sign-in or server work is ongoing.
- The tool should support several UI numbers, but G-MES reports must run
  sequentially in one application because only one tab is active, exports
  and modal popups are global, and parallelism would multiply browser
  profiles and sign-ins.
- Before shipping, the user asked for categorized bug/logic/edge-case
  reports, testing, history/skill updates, and synchronization with main.

### Communication lessons from the chats

The user is not a browser-automation engineer and repeatedly asked for
concise, plain-language progress. Future agents should report, in this
order:

1. What changed.
2. What worked, with evidence.
3. What failed, with the actual cause if known.
4. What the user should test next.

For a visible demo, narrate phases while they happen. For unattended work,
keep logs and screenshots detailed even if the user-facing summary is short.
If an Arabic keyboard layout produces unreadable text, confirm the intended
command before acting. If another agent or process cannot be observed because
Windows denied process access, say so instead of inferring that it is absent.

---

## 17. Safe workflow for the next agent

When extending or repairing the project:

1. Identify N-ERP, G-MES, shared CDP, presentation, profile, or test scope.
2. Read CLAUDE.md, this guide, and the relevant history phase.
3. Search existing code and gotchas before inventing a selector or timeout.
4. Use read-only inspection: gmes_inspect.py, gmes_find.py, gmes_data.py,
   gmes_probe_nexacro.py, gmes_dump.py, or the N-ERP mock. Avoid sensitive
   dataset dumps.
5. Reuse cdp_common, gmes_common, and gmes_core helpers.
6. Make the smallest evidence-based change.
7. Add a regression case when possible.
8. Add Symptom / Cause / Fix / Lesson to HISTORY.md in the same commit.
9. Verify screen, active tab, read-back controls, dataset change, requested
   result value/date, file existence/size, and failure screenshot.
10. Report what was proven and what remains an assumption.

The project’s most useful question is:

> What did the system actually prove, and what am I merely assuming?

That question is the experience this file is meant to preserve.
