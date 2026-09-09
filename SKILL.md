---
name: opening-nerp-tcode
description: Opens the NERP portal (https://nerps.sec.samsung.net) in Chrome via CDP automation, waits for the SAP Fiori/chatbot UI to load, types a given T-code (e.g. MB52, MB51) into the "Search Program" field, clicks "Go", fills selection-screen filter fields (e.g. Material, Plant) and clicks "Execute", and can export the resulting list to a genuine Excel (.xlsx) file via Shift+F4 / Ctrl+Shift+F7 / Shift+F7 / Ctrl+Shift+F9 / toolbar Export icon (whichever the report responds to). Use whenever asked to open NERP, search/run a T-code, filter its selection screen, "execute" on a T-code page, or "export to excel file".
---

# Opening NERP T-code

Automates the full NERP workflow via Chrome DevTools Protocol (CDP), not
keyboard/mouse-simulation hacks (SendKeys was tried repeatedly and never
reliably worked in this environment):

1. Open the NERP portal and search for a T-code (`search_tcode.py`).
2. Fill selection-screen filter fields and click **Execute** (`execute_filters.py`).
3. Export the resulting list to Excel (`export_to_excel.py`).

For interactive/standalone use outside a Claude Code conversation, there's
also **`run_nerp_workflow.py`** (or double-click **`NERP_Workflow.bat`** in
this folder) — it prompts the user for a T-code and any number of
`Label=Value` filters, then runs all three steps automatically end-to-end
with no further input needed. It always force-restarts Chrome fresh first
(see gotcha #15) and polls for the WebGUI screen to be ready before filling
filters (see gotcha #16) rather than assuming either is instant.

"Execute" always means: click the SAP **Execute** button (F8 / "Execute
Emphasized") on whatever selection screen is currently open — the location is
found dynamically each time (see step 2 below), not a fixed screen
coordinate.

"Export to excel file" always means: on whatever list/data screen is
currently open (post-Execute), try **Shift+F4**, then **Ctrl+Shift+F7**,
then **Shift+F7**, then **Ctrl+Shift+F9**, then finally clicking the
toolbar **Export icon** (`title="Export"`) and selecting **"Spreadsheet"**
from its dropdown — in that order, until one opens a recognized dialog —
then fill in `<T-code>_<YYYYMMDD_HHMMSS>.xlsx` and click through to confirm.
See step 4 below for why there are three different dialog flows depending
on which mechanism fires. (Shift+F4 does nothing detectable on some reports
like MB52's ALV list but directly opens flow A on others like MB51 — SAP
key bindings are per-transaction, see gotcha #17 — so it's tried first as a
harmless no-op when inapplicable, never a wasted step.)

## Known environment gotchas (all already solved by this skill)

1. **Corporate proxy blocks localhost CDP traffic.** `HTTP_PROXY`/`HTTPS_PROXY`
   env vars point at a corporate gateway with no `NO_PROXY` bypass, so even
   `http://localhost:9444/...` gets routed through the proxy and blocked
   ("403 URLBlocked" / Skyhigh Secure Web Gateway). Fix: set
   `NO_PROXY=localhost,127.0.0.1,::1` (and lowercase `no_proxy`) in the same
   PowerShell session before launching Chrome or Python.
2. **Chrome single-instance behavior.** If any Chrome process is already
   running, a new `chrome.exe --remote-debugging-port=9444` invocation just
   forwards to the existing instance and silently ignores the new flag — port
   9444 never opens. Fix: force-kill all `chrome` processes first, and launch
   with a dedicated `--user-data-dir` to guarantee a fresh instance.
3. **CDP websocket origin rejection.** Chrome rejects the DevTools websocket
   handshake with `403 Forbidden` unless launched with
   `--remote-allow-origins=*`.
4. **Stale websocket during long waits.** Holding a websocket open and idle
   during page load causes the next `recv()` to time out. Fix: close the
   websocket after navigating, wait with no open socket, then open a
   **fresh** websocket connection for each poll attempt. Originally this
   used a fixed `time.sleep(30)`, but page-load time varies a lot
   (chatbot widget init, network conditions), so `search_tcode.py` now
   polls every 2s for the "Go" button to actually appear (reconnecting
   fresh each attempt) instead of guessing a duration - it has exited in as
   little as 4s and has also needed well over 30s, both handled the same
   way. See gotcha #23 for the general principle this follows.
5. **`element.click()` does nothing on either the Fiori shell buttons or the
   classic WebGUI toolbar buttons** (the latter are `<div>`s wired to
   mousedown/mouseup, not real click handlers). Fix: get the element's
   `getBoundingClientRect()` via `Runtime.evaluate`, then simulate a real
   click using CDP's `Input.dispatchMouseEvent` (`mouseMoved` →
   `mousePressed` → `mouseReleased`) — see `click_element_by_rect()` in
   `cdp_common.py`.
6. **The T-code's selection screen (filter fields, Execute button) is NOT in
   the Fiori page's DOM at all.** After clicking "Go" on the T-code search,
   SAP GUI for HTML renders the actual screen in a *separate, cross-origin
   CDP target* — an `iframe`-type entry from `GET /json/list` whose URL
   contains `/sap/bc/gui/sap/its/webgui`. You cannot reach it via
   `contentDocument` from the main page (cross-origin); you must fetch
   `/json/list` again, find the target with `type == "iframe"` and
   `"webgui"` in its URL, and open a **separate websocket connection directly
   to that target's `webSocketDebuggerUrl`**. `get_webgui_tab()` in
   `cdp_common.py` does this.
7. **Selection-screen field IDs are unstable; field labels are not.** Dynpro
   fields get IDs like `M0:46:::2:34` that are regenerated per screen layout
   and shouldn't be hardcoded. Instead, match on each `<input>` element's
   `title` attribute (e.g. `"Material Number"`, `"Plant"`, `"Storage
   Location"`), which is the stable SAP field label. `execute_filters.py`
   does a case-insensitive substring match on `title`.
8. **`Page.captureScreenshot` fails with "Command can only be executed on
   top-level targets"** when called on the WebGUI iframe's websocket
   connection. It only works on the top-level `page`-type target (the Fiori
   shell tab) — screenshots still show the WebGUI content fine since it's
   rendered as a visual iframe within that page, you just can't call the
   CDP command through the iframe's own target. Useful for debugging unknown
   dialogs: connect to the `page` target and call `Page.captureScreenshot`,
   `Read` the resulting PNG.
9. **Text-based element lookup by exact string (e.g. finding a button
   labeled "Export to...") easily matches a huge ancestor container instead
   of the actual clickable element**, because `textContent` is inherited/
   concatenated up the tree (e.g. a hidden context-menu item containing the
   same words, or the whole toolbar). Fix: filter candidates to those with a
   non-zero, non-huge `getBoundingClientRect()` (i.e. actually visible) and
   short trimmed text length, then pick the smallest-area match — see
   `find_visible_leaf_by_text()` in `cdp_common.py`.
10. **The Export-As dialog's file-name input has a regenerated dynpro ID
    just like other fields**, so it's matched by its auto-populated default
    value pattern (`EXPORT_YYYYMMDD_HHMMSS`) via regex instead of by ID —
    see `export_to_excel.py`. This dialog is SAP's generic SALV "Export As"
    dialog (element ID prefix `SAPLSALV_GUI_CUL_CONFIGURATION...`), used
    across most SAP list/ALV reports, so this approach should generalize
    beyond MB52.
11. **Different SAP list types use genuinely different export mechanisms —
    there isn't one universal shortcut.** `export_to_excel.py` tries three
    shortcuts in order, detecting which dialog (if any) opened after each:
    - **Flow A** (Ctrl+Shift+F7, standard ALV grid reports like MB52):
      "Export As" dialog, filename defaults to `EXPORT_YYYYMMDD_HHMMSS` →
      click **"Export to..."** → a second "Enter file name to save" dialog
      → click **"OK"**.
    - **Flow B** (Shift+F7, hierarchical/tree list reports like
      ZRPPM400300's MRP list): skips straight to a single "Enter file name
      to save" dialog, filename defaults to something like
      `MRP_List_YYYYMMDD.XLSX` — **no intermediate "Export to..." button**,
      just fill the field and click **"OK"**.
    - **Flow C** (Ctrl+Shift+F9, e.g. ZRMMK121040's "Split xls" list — this
      is the same shortcut as the List menu → Export → Local File path):
      opens a "Save list in file..." **format-choice** dialog first
      (Unconverted / Text with Tabs / Rich Text / HTML / Clipboard, no
      direct Excel radio option) → select **"Text with Tabs"** → click the
      icon-only **"Continue"** button (found by `title` attribute, it has
      no usable visible text) → this opens the same kind of "Enter file
      name to save" dialog as flow B, but its **"Save as" dropdown**
      (`popupDialogFilterCbx`, opened via its dedicated arrow button
      `popupDialogFilterCbx-btn`) defaults to "Text Files (*.txt)" and must
      be switched to **"Spreadsheet Files (*.xlsx)"** — only then does
      picking "Text with Tabs" actually produce a real `.xlsx` file instead
      of a plain tab-separated text file. See `run_flow_c()` in
      `export_to_excel.py`.
    If a report responds to none of the three shortcuts (e.g. a
    single-record document view like CO03's order header, which isn't a
    list at all), don't guess further — report back to the user with a
    screenshot rather than trying more shortcuts or menu paths blindly.

12. **Multiple T-code sessions in the same browser can leave stale, blank
    WebGUI iframe targets behind, and position in the tabs list is NOT a
    reliable way to tell which one is current** — the stale one has shown
    up both before and after the real one across different tests. Fix:
    `get_webgui_tab()` connects to each candidate and counts its text
    inputs; the stale one is a near-blank placeholder (`document.title ==
    "SAP"`, ~1 input for the transaction-code box), while the live one has
    the actual screen's fields. Pick whichever has the most inputs, not
    whichever is first/last in the list.
13. **Dialogs opened by a keyboard shortcut don't always render within a
    fixed 2-second sleep** — a check right after `sleep(2)` can report "not
    found" even though the same dialog shows up in a screenshot taken a
    couple of seconds later. Fix: poll every ~0.5s for up to ~4-6s instead
    of a single fixed sleep before concluding a shortcut didn't do anything.
14. **A synthetic click on a dialog's "OK"/confirm button occasionally lands
    as focus-only rather than a full click-through** (button shows focused
    in a screenshot, dialog stays open). Fix: after clicking, poll for the
    success confirmation for several seconds and re-click once partway
    through the polling window if it hasn't appeared yet, rather than
    treating a single click + single check as final.
15. **A long-lived Chrome CDP session accumulates stale duplicate tabs
    across repeated T-code searches** — 11+ duplicate "N-ERP Home" page
    tabs turned up after repeated testing in a single session, which slows
    down `GET /json/list` and makes page-tab lookups (`next(t for t in tabs
    if t.get("type")=="page")`) prone to picking a stale tab instead of the
    active one. This compounds with gotcha #12's stale-iframe problem.
    `run_nerp_workflow.py` avoids this by force-killing and relaunching
    Chrome fresh (`taskkill /F /IM chrome.exe`, then relaunch) at the start
    of every run rather than reusing whatever CDP session already exists.
16. **Chaining scripts back-to-back with no natural pause between them
    exposes timing gaps that manual step-by-step PowerShell calls
    papered over.** When a human runs each step as a separate tool call,
    the gap between calls incidentally gives Chrome time to settle; a
    fully-automated orchestrator that calls `search_tcode.main()` then
    immediately `execute_filters.main()` can hit "WebGUI iframe target not
    found" because the iframe hasn't spun up yet right after the Go-click
    returns. Fix: poll for `get_webgui_tab()` to return non-None (see
    `wait_for_webgui_tab()` in `run_nerp_workflow.py`) before proceeding,
    rather than assuming the previous step's completion means the next
    target is immediately ready.
17. **Different t-codes can bind the SAME shortcut to different actions —
    Shift+F4 is not universally a no-op.** On MB52 it did nothing detectable;
    on MB51 it directly opened the flow-A "Export As" dialog (SAP GUI status
    key bindings are configured per-transaction, not globally). This is
    exactly why `export_to_excel.py` tries shortcuts in order and detects
    the resulting dialog by its content rather than assuming a fixed
    shortcut-to-flow mapping.
18. **Only the very first dialog-detection step polled for slow rendering —
    the follow-up "Export to..." and "OK" button lookups inside flow A were
    single-shot with just a fixed `sleep(1.5)` beforehand.** This surfaced as
    a real failure: on MB51, Shift+F4's route to the "Export to..." →
    "Enter file name to save" transition rendered slower than 1.5s, so the
    single-shot "OK" lookup found nothing and errored out immediately
    (`ERROR: 'OK' confirmation button not found`), even though the dialog
    appeared moments later. Fix: `click_button_by_text_polled()` in
    `export_to_excel.py` replaces the single-shot lookups for both
    "Export to..." and the final "OK" with the same poll-don't-assume
    pattern already used elsewhere (gotcha #13) — every button lookup in
    the export chain should tolerate variable render speed, not just the
    first one.
19. **A final export mechanism exists on reports with neither the F7/F9
    shortcuts nor a keyboard binding at all: a toolbar "Export" icon**
    (small icon + dropdown-chevron button, `title="Export"` exactly, e.g.
    id `_MB_EXPORT102` on ZRPPD410200's "Production Order Change History
    Report"). Clicking it reveals a dropdown (Spreadsheet / Local File /
    Send / SAPoffice Folders / ABC Analys. / HTML download); clicking
    **"Spreadsheet"** lands in the exact same flow-A "Export As" dialog as
    Ctrl+Shift+F7, so it reuses flow A's existing completion steps. This is
    a mouse-driven trigger, not a keyboard shortcut, and is tried last
    (`trigger_export_icon()` in `export_to_excel.py`) after all four
    shortcuts fail to open a recognized dialog.
20. **`find_visible_leaf_by_text()`'s visibility check (non-zero
    width/height) was not sufficient — some dropdown/menu widgets render
    off-screen first to measure their size before repositioning into
    view.** This caused a real, silent failure: clicking the Export icon's
    "Spreadsheet" dropdown item was found and clicked at `y: -99984` (an
    off-screen pre-render position with non-zero width/height), so the
    click hit nothing and the whole flow failed with no error - it just
    looked like "no dialog opened". Fix: `find_visible_leaf_by_text()` in
    `cdp_common.py` now also requires the element's bounding box to
    intersect the actual viewport (`r.bottom > 0 && r.right > 0 && r.top <
    window.innerHeight && r.left < window.innerWidth`), not just be
    non-zero in size. This fix is in the shared helper, so it protects
    every button lookup across the whole skill, not just the Export icon.
21. **Pressing Escape to "close a leftover dropdown" during manual
    debugging instead navigated back to the selection screen entirely** —
    in this SAP GUI context Escape is bound like Back/F3, not
    close-popup-only. Don't use Escape as a cleanup step when debugging a
    stuck dropdown; re-click Execute to return to the results screen
    instead, or take a screenshot first to confirm what will actually be
    dismissed.
22. **`taskkill /F /IM chrome.exe` simulates a crash, and reusing the same
    `--user-data-dir` across restarts lets Chrome's session-restore
    silently reopen an old, completely unrelated tab from a previous test**
    (seen firsthand: after a forced restart, `search_tcode.py`'s "New Tab"
    connection landed on a stale "Stock Overview: Basic List" screen for a
    totally different material, from an old test many turns earlier - not
    MB51 at all). Every subsequent step then silently operates on the wrong
    screen with no error, since the page and iframe are perfectly valid,
    just stale. Fix: delete the profile directory before relaunching
    (`Remove-Item -Recurse -Force $profileDir`), not just kill the process
    - `run_nerp_workflow.py`'s `ensure_chrome_running()` should do this too,
    not only `taskkill`. Always sanity-check the page title after opening a
    t-code matches what's expected before trusting downstream steps.
23. **A large export (hundreds of rows) can leave the "Enter file name to
    save" dialog behind a "Stop Application" loading indicator for well
    over 20 seconds** while SAP prepares the file, and how long that takes
    isn't predictable from the outside - a duration-tuned timeout will
    always be guessable-wrong for some dataset size. Since
    `click_button_by_text_polled()`'s loop already exits the instant the
    target is detected, the fix is to make the safety cap generous (e.g.
    120s) rather than trying to estimate the "right" duration - a big cap
    costs nothing when the dialog appears quickly, and is what actually
    matters for slow exports. Apply this same reasoning anywhere a step
    waits on SAP server-side processing, not just this one dialog.
24. **The original fixed `time.sleep(30)` for the NERP portal's initial
    load (gotcha #4) had the same guessable-wrong problem as gotcha #23,
    but in the *user-visible* direction: real network conditions can make
    the page slower than 30s (a hard failure), while on a fast connection
    30s is needlessly slow (seen loading in as little as 4s in later
    testing).** `search_tcode.py` no longer sleeps a fixed duration at all
    - it polls every 2s, reconnecting fresh each attempt (see gotcha #4),
    checking whether the "Go" button has actually rendered, with a ~4
    minute safety cap. This is the same poll-until-detected-with-generous-
    cap pattern as gotcha #23, applied to page load instead of dialog
    appearance - don't reintroduce a fixed sleep here or anywhere similar
    just because "it usually works in N seconds."
25. **The same principle applies to every transition in the pipeline, not
    just page load and export dialogs: the selection screen appearing
    after search, and the result data page appearing after Execute, both
    used to be bridged by manual fixed sleeps** (`wait_for_webgui_tab()`'s
    old 15s cap in `run_nerp_workflow.py`, and ad-hoc
    `Start-Sleep`/`time.sleep()` calls between `execute_filters.py` and
    `export_to_excel.py` during manual testing throughout this
    conversation). Fixed. `wait_for_webgui_tab()`'s cap is now a generous
    120s safety net rather than a tuned 15s guess. `execute_filters.py`
    itself now waits for the result page after clicking Execute, via
    `wait_for_busy_indicator_clear()` in `cdp_common.py` - it polls the
    generic SAP WebGUI busy/loading indicator (`hiddenLoadingToolbarButton`,
    part of the shell chrome, not report-specific) until it appears-then-
    disappears (normal case) or never appears at all within a short grace
    window (fast operation, already done). This means callers - including
    `run_nerp_workflow.py` and any manual step-by-step invocation - no
    longer need an extra sleep between Execute and the next step at all.

## Steps

### Step 1 — launch Chrome with CDP (one PowerShell call; env vars don't persist across calls)

```powershell
$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = "localhost,127.0.0.1,::1"

Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$debugProfile = "$env:TEMP\chrome_cdp_profile"
Start-Process -FilePath $chromePath -ArgumentList `
  "--remote-debugging-port=9444", "--remote-allow-origins=*", `
  "--user-data-dir=$debugProfile", "--no-first-run", "--no-default-browser-check"

Start-Sleep -Seconds 4
netstat -ano | Select-String ":9444"   # confirm LISTENING before continuing
```

Skip this step if Chrome is already running with CDP on 9444 from an earlier
step in the same conversation (check `netstat` first instead of blindly
restarting — restarting loses the currently-open T-code screen).

### Step 2 — open the T-code

```powershell
$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = "localhost,127.0.0.1,::1"
python "C:\Users\a.selim\.claude\skills\opening-nerp-tcode\search_tcode.py" MB51
```

Run with `run_in_background: true` (it polls until the "Go" button appears
rather than a fixed wait — typically a few seconds, but can take much
longer under slow network conditions, up to a ~4 minute safety cap) and
wait for the task-completion notification — don't poll yourself. If it
fails with a `websocket`-not-installed error:
`python -m pip install websocket-client -q`.

### Step 3 — fill filters and Execute

```powershell
$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = "localhost,127.0.0.1,::1"
python "C:\Users\a.selim\.claude\skills\opening-nerp-tcode\execute_filters.py" "Material Number=SM-A137FLBHMEB" "Plant=P703"
```

- Pass zero or more `"Field Label=value"` arguments; each label is matched
  case-insensitively as a substring against the input's `title` attribute.
  If you don't know the exact label wording, first inspect the WebGUI target
  (see the inline JS pattern in this skill's design notes / prior
  conversation) to list all input `title`s before guessing.
- Call with no arguments to just click Execute without changing any filters.
- This step is independent of Step 2's wait — it connects directly to
  whatever WebGUI target is currently open.
- After clicking Execute, it waits internally for the result data page to
  actually finish loading (polling the busy indicator - see gotcha #25)
  before returning. No manual sleep is needed before Step 4, regardless of
  how large the result set is.

### Step 4 — export to excel file

```powershell
$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = "localhost,127.0.0.1,::1"
python "C:\Users\a.selim\.claude\skills\opening-nerp-tcode\export_to_excel.py" MB52
```

- The single argument is the T-code, used as the filename prefix
  (`<T-code>_<YYYYMMDD_HHMMSS>.xlsx`).
- Must be run after Step 3 (Execute) so a data list is actually on screen —
  it operates on whatever WebGUI target is currently open.
- Success is confirmed by the script itself: it checks the page for the
  status-bar text `Download ... .xlsx` after clicking OK (polling for a few
  seconds, re-clicking OK once if needed — see gotchas #13-14), and prints
  `SUCCESS: Export completed as '<filename>.xlsx' (flow A|B|C)`. If it
  instead prints a `WARNING`, take a screenshot of the top-level `page`
  target (see gotcha #8) before assuming it failed — it may have actually
  succeeded just after the polling window closed.
- If it prints `ERROR: No recognized export dialog found after trying
  Shift+F4, Ctrl+Shift+F7, Shift+F7, Ctrl+Shift+F9, and the Export icon`,
  this report likely isn't a list at all (e.g. a single-record document
  view) — take a screenshot and ask the user how to proceed rather than
  guessing further.
- The file lands in the SAP GUI download destination shown in the dialog
  (e.g. `Z:\<filename>.xlsx` in this environment).

### Step 5 (alternative) — standalone interactive orchestrator

Instead of running Steps 1-4 individually, `run_nerp_workflow.py` (or
`NERP_Workflow.bat`) does the whole thing in one interactive run — useful
for handing off to a user who wants to run this themselves without going
through a conversation:

```
python "C:\Users\a.selim\.claude\skills\opening-nerp-tcode\run_nerp_workflow.py"
```

It prompts for a T-code, then repeatedly prompts for `Label=Value` filters
(blank line to finish, or immediately for none), then runs open → fill
filters/Execute → export automatically, printing progress and pausing with
"Press Enter to exit..." at the end (or on the first failure) so the
console window doesn't vanish when double-clicked from Explorer.

Note this always force-restarts Chrome (gotcha #15) and reads its own
filter labels/values from interactive stdin rather than argv — if invoking
it programmatically (not interactively), pipe newline-separated
`tcode\nLabel=Value\n...\n\n` into stdin instead of calling
`search_tcode.main()`/`execute_filters.main()`/`export_to_excel.py`
directly.

### General notes

- Always confirm success via the script's printed JSON/log output, then ask
  the user to visually confirm in the Chrome window — headless verification
  of the actual rendered data isn't available.
- If a field or the Execute button isn't found, the WebGUI target may not
  have finished rendering yet, or the field label wording differs from what
  was guessed — re-run the inspection pattern (`document.querySelectorAll('input')`
  mapped to `{id, title, value}`) against the WebGUI target before retrying.
