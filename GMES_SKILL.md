---
name: gmes-automation
description: Automates Samsung G-MES (http://seegmes4.sec.samsung.net, a Nexacro application) through Chrome DevTools Protocol - signs in unattended with a DPAPI-stored Knox credential via AD SSO, clears the Notice popups, opens work screens, sets filter dates and Division, runs an Inquiry, reads whole result sets out of the Nexacro data layer, and exports with GMES's own Excel download. Use whenever asked to open GMES, log in to GMES, run or schedule a GMES report, read GMES data, or export a GMES screen to Excel.
---

# G-MES automation

G-MES is a **Nexacro** application, not SAP. It renders real DOM elements
with stable, meaningful ids, which makes it more tractable than N-ERP's
WebGUI — but it hides its data behind a JavaScript object model, and several
of its behaviours will silently produce wrong results if taken at face
value.

Read [CLAUDE.md](CLAUDE.md) before changing anything here, and record what
you learn in [HISTORY.md](HISTORY.md).

## Setup (once per machine)

```powershell
python -m pip install -r requirements.txt
python gmes_credentials.py set        # opens a dialog; stores with Windows DPAPI
```

## Quick reference

All of the mechanism lives in **`gmes_core.py`**. Everything below is a
command around it.

| Task | Command |
|---|---|
| **The basic run** | `gmes run P1112UM00 --division VD --from 20260909 --to 20260909` |
| **Interactive, prompts for everything** | `python run_gmes_workflow.py` or `GMES_Workflow.bat` |
| **See what a screen offers** | `python gmes_report.py describe P1112UM00` |
| Check the setup without querying | `python gmes_report.py run P1112UM00 --division VD --dry-run` |
| Forget what was learned about a screen | `gmes run P1112UM00 ... --relearn` |
| Find a screen when you don't know its code | `python gmes_report.py find "production plan"` |
| Set a left-panel option | `python gmes_report.py run P1112UM00 --option PLANT --option "Create Date"` |
| Set any filter, bound or not | `python gmes_report.py run P1112UM00 --set "Production Order=011074232146"` |
| Choose the grid on a master-detail screen | `python gmes_report.py run <UI> --grid dsDetail` |
| Refuse to export the wrong day | `python gmes_report.py run <UI> --date 20260908 --verify planYmd` |
| Several reports in one run | `python gmes_report.py run P1112UM00 P1111UM00 --division VD --days-back 1` |
| A JSON record of the run | `python gmes_report.py run <UI> --manifest run.json` |
| **Guided demo of everything below** | `python gmes_demo.py` |
| **Open any screen (the "T-code")** | `python gmes_open_screen.py P1112UM00` |
| Open by name | `python gmes_open_screen.py "Work Calendar"` |
| Find a screen's code | `python gmes_open_screen.py --find "production plan"` |
| What is open right now | `python gmes_open_screen.py --current` |
| Nightly Production Plan export | `python gmes_daily_prodplan.py` |
| A specific plan date | `python gmes_daily_prodplan.py --date 20260901` |
| A different division | `python gmes_daily_prodplan.py --division MOBILE` |
| Sign in only | `python gmes_login.py` |
| Where am I? | `python gmes_login.py --status` |
| First contact / reconnaissance | `python gmes_connect.py` |
| What is on screen | `python gmes_inspect.py` |
| Find a control anywhere | `python gmes_find.py Inquiry` |
| Open screens and datasets | `python gmes_data.py forms` |
| Read a dataset | `python gmes_data.py read P1112WM00 dsMasterProdPlan 20` |
| Export a dataset | `python gmes_data.py csv P1112WM00 dsMasterProdPlan out.csv` |
| Inspect a JS object | `python gmes_dump.py "nexacro.getApplication().mainframe"` |

**Chrome must be closed** before the first launch of the day, because Chrome
will not hand over a profile already in use. The scripts detect this and say
so rather than failing obscurely.

## Screen map — Production Plan by Order(Line)

Breadcrumb: `PPM > Production Plan > Prod. Plan Inquiry > Detail Schedule >
Production Plan by Order(Line) [ P1112UM00 > P1112WM00 ]`

| Screen code | Role | Key datasets |
|---|---|---|
| `P1112WF00` | left filter panel | `dsFilterDVO` — `paramFromDate`, `paramEndDate` (YYYYMMDD) |
| `P1112WM00` | results | `dsMasterProdPlan` — 140 columns |
| `OrgCategory_GDS` | Org tab tree | `dsCatCommonTreeNodeDVO` — 34 rows; VD is `^V^C712A^T001` |

Fixed shell ids (safe to hardcode — there is only ever one of each):

```
mainframe.vFrameSet1.vFrameSet2.topFrame.form.btnUserInfo      signed-in user
mainframe.vFrameSet1.vFrameSet2.mdiFrame.form.btnExcel         Excel Download
mainframe.vFrameSet1.loginFrame.form.divLogin.form.btnAdSSO    AD SSO Login
```

## Known gotchas (all already solved by this skill)

1. **Chrome 136+ silently refuses to debug the default profile.**
   `--remote-debugging-port` is *ignored*, not rejected, whenever
   `--user-data-dir` is the default profile directory — a security fix that
   stopped malware reading cookies out of a live browser via DevTools. The
   port simply never opens, which looks exactly like a launch failure.
   Fix: `clone_user_profile()` copies the profile to
   `%LOCALAPPDATA%\Google\Chrome\CDP Profile` (excluding caches, 928 MB →
   338 MB) and Chrome is driven against the copy. Extensions and saved
   logins survive; session-only cookies do not, so the site may ask for a
   one-off sign-in inside the copy. **The copy is never deleted, and the
   real profile is never touched.**

2. **AD SSO is not automatic.** It opens a Samsung ADFS window
   (`stseu.secsso.net`) asking for a Knox ID and password. Credentials come
   from the DPAPI store; they are typed straight into the browser and never
   printed, logged, or passed as arguments.

3. **"Signed in" cannot be detected by the absence of the Login button.**
   Nexacro keeps the login frame in the DOM and merely hides it, so that
   test never becomes true. Check for the user-name button in the top bar
   (`topFrame.form.btnUserInfo`) instead.

4. **The Notice popup appears seconds *after* sign-in completes.** Checking
   once right after the user name appears reports "no popups" and then the
   popup blocks everything behind it. `close_popups_when_they_appear()`
   waits for the first one, closes it, and keeps watching — a real run
   closed two in succession.

5. **Close popups by type, not by name.** The Notice window's id contains
   Korean text (`...portalFrame.공지사항.titlebar.closebutton`). Matching that
   would close exactly one popup on one screen forever. Match the class
   Nexacro gives floating child windows: `.TitleBarControl.titlebarChildFrame`
   → `.closebutton`. Scoped to child frames so the user's work screen is
   never closed.

6. **The Excel export dialog is also a child popup**, so the popup closer
   would close it. Run the closer **only during sign-in**, never around an
   export.

7. **A work screen's ids are renumbered on every open.** The same Inquiry
   button was `winPPM0219_0_516` on one visit and `winPPM0219_0_315` an hour
   later. Nothing inside a work screen may be addressed by full id — match
   the screen code, the CSS class (`btn_LF_Search_New`), or the label.

8. **The breadcrumb is the address.** It ends with the screen codes
   (`[ P1112UM00 > P1112WM00 ]`). Those are stable. The top search box also
   accepts a ScreenID, which is the intended way to reach a screen without
   walking menus.

9. **A Nexacro grid only builds the rows you can see.** Reading the page
   silently truncates a large result — a 5,000-row report becoming the 20
   rows on screen, with the job reporting success. Read the Dataset.

10. **Two traps make the Nexacro app look empty.** Child frames live in
    `_frames`, an `ObjectArray` with numeric indexing — there is no `frames`
    property. And a work screen is **not a frame**: it is loaded into nested
    `Div` components, each carrying its own `.form`. Walking only frames
    finds an empty `WorkMain` shell and nothing else.

11. **A truncating safety cap hides the answer.** The form walk capped at 60;
    the application has 206 forms, so the target screen appeared not to
    exist at all.

12. **Missing Division = zero rows, with no error.** The screen shows
    "Select Search Criteria" and an empty grid. Tick the division in the Org
    tree — `_checked = 1` on the matching row of
    `OrgCategory_GDS.dsCatCommonTreeNodeDVO` — and the UI checkbox follows.
    Find the row by `commonName`, never by row number: the tree is built
    from the user's permissions.

13. **Dates are set through the dataset, not the calendar widget.** Writing
    `paramFromDate` / `paramEndDate` (YYYYMMDD) into `P1112WF00.dsFilterDVO`
    updates the visible date box, because Nexacro binds the two.

14. **An empty result set does not mean the query finished.** Nexacro clears
    the dataset the instant Inquiry is pressed and refills it when the
    server answers, so the count sits at 0 for the whole round trip.
    Treating stable zeros as "settled" reported 0 rows and refused to export
    while 790 rows were on their way. Settle only on a count **above zero**
    that has stopped moving, and give an all-zero run a long grace period
    before concluding there is genuinely no data.

15. **The Excel toolbar icon opens a dialog, it does not download.**
    `PopupExcelExport` — "Save to Excel", grid already ticked, "save a
    single file" ticked. The file arrives only after **OK**.

16. **Chrome's download redirect dies with the connection that set it.**
    `Browser.setDownloadBehavior` must be issued on the *same* open CDP
    connection that does the clicking; setting it from a connection that is
    then closed leaves the file in the user's Downloads folder. Watch that
    folder as a fallback anyway.

17. **The exported workbook is DRM-encrypted.** It begins
    `<## NASCA DRM FILE - VER1.00 ##>` (Samsung NASCA document rights
    management). It opens normally in Excel on a machine running the DRM
    client, but **no library can parse it** — `openpyxl` and `pandas` see a
    corrupt file. If anything downstream must read the data, write a CSV
    from the dataset alongside it.

18. **The dataset carries filler rows the grid hides.** 85 rows with no
    `poNo` and no `masterLine`. 875 − 85 = 790, matching the screen's own
    total exactly — and explaining an earlier unexplained 701-vs-784 gap.
    Drop rows with an empty `poNo` so the count agrees with what the user
    sees. GMES's own Excel export is unaffected, since it exports the grid.

19. **Verify the result date before exporting.** A stale result set looks
    exactly like a fresh one, and an export of the wrong day is worse than
    no export. `verify_result_date()` refuses to continue on a mismatch.

20. **`input()` may have no keyboard.** Launched from a runner without an
    interactive stdin, the credential prompt died with `EOFError`. Fall back
    to a Tk dialog when `stdin.isatty()` is false.

21. **`menuId` is G-MES's T-code, and the whole directory is client-side.**
    `gdsMenuList` (1177 rows) holds every screen the account can reach — 809
    of them — with `menuId` (PPM0219), `sysScreenId` (P1112UM00),
    `enMsgCont` / `koMsgCont`, and `screenSn`, the ancestor chain that
    reproduces the on-screen breadcrumb exactly. `menuId` is the identity
    that matters: it is what `gdsOpenMenu` records, and what the window is
    named after (`winPPM0219_0_603`).
    **Do not use `gdsMenuList_`.** It looks like the same catalogue but its
    titles are Korean only and its menuIds are a different series (`PM0001`
    vs `PPM0219`), so searching or joining it in English silently returns
    nothing.

22. **The search box must be typed into with real key events.** Setting the
    value through Nexacro's own `set_value()` fills the box and searches
    nothing — the suggestion list is produced by the control's `onkeyup`
    handler. Click the box to focus it, then send per-character
    keyDown/char/keyUp.

23. **The Notice popup is MODAL and swallows every click silently.** While
    it is open the application is greyed out; the search button appeared
    completely dead until the popup was closed first. Clear popups before
    interacting with anything.

24. **Click the result GRID row, not the detail panel.** Suggestions live in
    `integratedSearch.form.grdResult`, bound to `dsSearchResult`; the row to
    click is `grdResult.body.gridrow_<n>.cell_<n>_0`. The popup also shows a
    detail panel (`divDetail.form.staTitle`) carrying the same text — it is
    the obvious visual match, and clicking it opens nothing at all. Read
    `dsSearchResult` to choose the row by data, then click that row.

25. **Open is not the same as active.** G-MES keeps every opened screen
    alive behind tabs. A background screen still accepts dataset writes, so
    filters can be applied to one screen while the Inquiry click lands on
    whichever screen is actually in front. That produced a run which set the
    date and division correctly, queried a completely different report, and
    reported zero rows. Activate the tab (`mdiFrame.form.divTab.form.TAB_<winId>`)
    and confirm the window became visible before acting.

26. **Dataset dumps can contain live session tokens.** The integrated-search
    form's `dsAnyframeDVO` carries `tokenId` and `refreshTokenId` — full
    JWTs for the signed-in session. Never paste raw dataset output into
    documentation, commit messages, issues or chat. Print only the columns
    needed.

27. **Clicking AD SSO does not always open an SSO window.** When a session
    cookie has survived in the profile copy, G-MES signs straight back in
    and no Samsung ADFS page is ever shown. Waiting only for that window
    failed a run with "the Samsung SSO window never opened" while the user
    was already signed in. Wait for **either** the SSO window **or** a
    completed sign-in, whichever arrives first.

28. **The "extra" rows are SUBTOTALS — LINE SUM and PROC SUM.** The result
    dataset carries rows with an empty `poNo`, `masterLine` and `modelCode`
    but the same `planQty` / `acrsQty` as the data row above them. On screen
    the grid renders those rows labelled **LINE SUM** and **PROC SUM**: the
    labels are added by the grid at render time and are *not* stored in the
    dataset, which is why they look blank when read from the data layer.
    That explains the arithmetic exactly — 875 − 85 = 790, the grid's own
    total — and it means dropping rows with an empty `poNo` is correct for a
    data extract, because it drops subtotals rather than data.
    *(Previously recorded here as an unexplained inference; confirmed by
    inspecting a single-PO result, where 1 data row came with 3 subtotal
    rows carrying identical quantities.)*

29. **Filters can be discovered, not hand-taught — `form.binds` is the map.**
    Every Nexacro form carries a binding table linking each control to the
    dataset column behind it:
    `divBasic.form.divCal.form.mskDateFrom → dsFilterDVO.paramFromDate`.
    Read it and a screen describes its own filters, with the label rendered
    beside each control. The result grid is found the same way, via its
    `binddataset`. Three caveats learned immediately:
    - Bound **Statics** are computed outputs (`staPlanQty`, `staProgRate`),
      not filters. Classify by the control-name prefix: `edt/msk/cbo/chk/
      rdo/cal/spn` are inputs, `sta/img/btn` are displays.
    - The shell's own forms (`WorkMainTitle`, `MyMenu`, `LeftMain`) carry
      binds that belong to the frame, not the report. Exclude them.
    - **Not every screen binds its filters.** `Q2241UM00` binds none and
      sets them in code, so a bind-only tool reports "no filters" and looks
      broken. List the visible-but-unbound inputs too, and say plainly that
      they cannot be set through a dataset.

30. **Never poll a result dataset by a hardcoded name when the screen can
    vary.** Running *Production Plan by Model* with the Production Plan
    job's inquiry helper reported **875 rows** — the count still sitting in
    the previous screen's `dsMasterProdPlan` — when that screen had actually
    returned **17**. The export was correct, because it used the discovered
    dataset; only the number and the settle-wait were wrong, which is the
    more dangerous combination: the file is right, the log lies, and nobody
    checks. Poll the dataset discovered on the screen being run, and require
    the count to be seen **changing** so a dataset left populated by a
    previous run is not mistaken for a finished query.

31. **Run multiple reports sequentially, never in parallel.** One tab is in
    front at a time and a background screen still accepts filter writes;
    the Excel button and its dialog are global to the application; modal
    popups block everything. Parallelism would need separate Chrome
    instances, profile copies and SSO sign-ins for a gain measured against
    ~12-30s of server time per report. Isolate each screen instead, so one
    failure does not stop the rest.

32. **The left panel carries filter dimensions that are not "filters".**
    Each of these changes what a query returns, and each is a labelled
    button or checkbox — not a bound field, so bind-discovery alone misses
    every one of them:

    | Option | Effect |
    |---|---|
    | `Org` / `Prod` / `Fac` / `Proc` | which category tree the selection comes from |
    | `STD` / `PLANT` | the organisation attribute |
    | `Including Past Org.` | include closed organisations |
    | `Plan Date` / `Create Date` | **which date the period means** |
    | `General` / `Compare` / `OI` | the search mode |
    | Quick View entries | e.g. Master vs Detail Prod. Plan — a different result set |

    Nexacro encodes the state in the CSS class: `_Sel`, `Category_Sel` or
    `ToggleSearchV2` mean chosen; `_Dis` or `_Default` mean not. So they can
    be listed with their current state and set by label —
    `--option PLANT`, `--option "Create Date"`. Setting one is verified by
    re-reading the class, never assumed. Apply them **before** the Division
    and the filters: switching a category tab or Quick View rebuilds the
    panel and discards what was set.

33. **A generic CSV must not guess which column is the key.** The Production
    Plan job drops rows with no `poNo`; on an unknown screen there is no
    equivalent to drop on. Filtering one PO returned **four** dataset rows
    for a single visible line — three continuation rows the grid merges.
    The generic exporter therefore drops only completely empty rows and
    reports both counts. Silently discarding rows on a screen whose shape
    is unknown would be worse than a larger file.

34. **Filters PERSIST on an open screen, and are inherited silently.** G-MES
    keeps a screen alive behind its tab, so a value typed into a filter
    stays there for every later run. A run asking only for a date returned
    **zero rows** because a Production Order from the previous run was still
    in the box — the date was right, the division was right, and the answer
    was empty with nothing to indicate why.
    Before applying a run's own filters, blank the free-text (`edt`) fields
    the caller did not name. Do **not** blanket-clear: combos and checkboxes
    hold meaningful defaults (`paramTecoYn` = "All", a status list =
    "1^2^3^4") and emptying those breaks the query a different way.

35. **Accept what people actually type.** Two real failures in one session:
    `vd` did not match the Org tree's `VD` because the comparison was
    case-sensitive — with the answer sitting in the error message it
    printed — and `2026-09-07` was written verbatim into a filter that
    stores `YYYYMMDD`, so the query silently answered something else.
    Match organisation and screen names case-insensitively, normalise dates
    to `YYYYMMDD`, and **reject** anything that is not a real calendar date
    rather than passing it through.

36. **Address the DevTools endpoint by `127.0.0.1`, never `localhost`.** On
    Windows, `localhost` resolves to `::1` first and Chrome listens on IPv4
    only, so every call waits for the IPv6 attempt to fail. Measured: **2.05s
    per `/json/list` via `localhost` against 0.013s via `127.0.0.1`** — a
    150x difference. It is paid by every target lookup *and* every websocket
    connect, because Chrome hands back `webSocketDebuggerUrl` values pointing
    at `localhost`, so those must be rewritten too (`cdp_common.ipv4()`).
    Fixing this took the startup path from 12.5s to 0.41s.

37. **Only wait for the Notice popup after an actual sign-in.** It arrives a
    few seconds *after* the user name appears, so a fresh sign-in has to
    watch for it (gotcha #4). But that 45-second vigil ran on every
    invocation, including sessions that were already signed in, where any
    popup would already be on screen. Every command paid it before doing any
    work: `gmes_login.py` took **58.9 seconds** on an already-signed-in
    session and closed nothing. Wait when signing in; sweep once otherwise.

38. **A control with no binding is still driveable — with real keys.**
    `form.binds` finds the fields a screen declares; a screen that sets its
    filters in code (`Q2241UM00`) declares none. Those controls cannot be
    written through a dataset, but they can be typed into, because Nexacro
    reacts to key events and not to a value assignment — the same property
    that makes the top search box searchable (#22). Click, Ctrl+A, Delete,
    per-character keyDown/char/keyUp, Tab to commit, then **read the control
    back**: an unfocused Nexacro edit is a `div` carrying text, a focused one
    renders a real `<input>`, so the read has to handle both.

39. **Date fields are not all called `fromDate`, and are not all 8 digits.**
    Screens store `planYmd`, `stdYm`, `paramPeriod1`. Recognise a date by
    whole words in the column or label (`date`, `ymd`, `ym`, `dt`, `period`,
    `day`) or by the control type — `msk` and `cal` are Nexacro's masked
    edit and calendar. Match **words**, never substrings: `paramVendorCode`
    contains "end". And write the width the field already holds — a `YYYYMM`
    field given eight digits is accepted, and the query then answers a
    different question.

40. **Every left-panel category tab has a tree of its own.** Org / Prod /
    Fac / Proc are not one tree with four filters. Find them by shape — a
    dataset with a `commonName` column and a `_checked` flag — and choose by
    data: the tree that actually contains the name asked for. `OrgCategory_GDS
    .dsCatCommonTreeNodeDVO` is the Org one, not the only one.

41. **A tick in a category tree persists exactly as a typed filter does.**
    The screen stays alive behind its tab, so a division ticked by one run is
    still ticked for the next, and a run asking for a different one queries
    both. Clear the ticks the run did not ask for, and say which were
    cleared.

42. **More than one grid can be bound on the same screen.** Master-detail
    screens have two, and "the biggest visible grid" is then a coin toss with
    no error either way. Report the ambiguity and let the caller name the
    grid.

## The nightly job

```powershell
python gmes_daily_prodplan.py [--date YYYYMMDD] [--days-back N]
                              [--division VD] [--output-dir PATH]
                              [--no-csv] [--keep-open]
```

Steps, each verified rather than assumed:

1. Start Chrome on the profile copy; sign in via AD SSO if needed.
2. Clear Notice popups.
3. Write the plan date into `P1112WF00.dsFilterDVO`.
4. Tick the Division in the Org tree.
5. Click **Inquiry**; wait for the result count to settle above zero.
6. Confirm the returned rows carry the requested `planYmd`.
7. Click **Excel Download** → **OK** on the Save-to-Excel dialog.
8. Move the file to `Data Hub Folder/GMES/` as
   `Production Plan by Order(Line)_<YYYYMMDD>_<HHMMSS>.xlsx`.
9. Write a machine-readable CSV alongside it, filler rows removed.

Exit code 0 on success; 1 with a diagnostic screenshot on any failure.
