GMES AUTOMATION 2.0 - record any G-MES screen once, then run it, batch it, schedule it
=====================================================================================

WHAT IT IS
  A window for the whole factory. Give it any G-MES UI number: it reads the screen,
  you choose the scope once (division, dates, filters), and it RECORDS what a
  successful run proved. From then on the screen runs with one click, in a batch with
  others, or by itself every morning. It only reads G-MES and downloads - it never
  saves, submits, approves or deletes anything there.

START
  Double-click  Start_GMES.bat  (it opens GMES_Automation.exe). Chrome or Edge must be
  on the PC. Nothing else has to be installed for the .exe.
  The window is a page shown in an Edge / Chrome APP window (no tabs, no address bar).
  It runs on its own small profile in data\ui-browser - your own browser and the
  automation browser are not touched. Starting the program again while it is open just
  opens another window on it. When the window is closed and nothing is running, the
  program ends by itself (and closes the automation browser) within about a minute.

FIRST TIME ON A PC - "Account & Browser"
  - Save YOUR Knox / G-MES login (twice, then Save login). It is encrypted with
    Windows for your Windows account on this PC only; nobody else can read it, it is
    never shown or written to a log. Each person saves their own login.
  - Browser: Automatic (the Windows default) is right for almost everyone. On the
    first run the tool makes its OWN copy of that browser's profile, once, so a G-MES
    session you already have comes along. Your own browser is only read; its
    extensions are switched off in the automation browser. If the browser is open
    during that first copy, close it once when asked.
  - "Test sign-in" checks it once. Do not sign in many times in a row: a burst of
    sign-ins can stop the Samsung sign-in window from opening for a while.

RECORD A SCREEN - "Record a screen"
  1 Screen     type the UI number (P1112UM00) and press Describe. Not sure of the
               number? Type words from its name and press Find.
  2 Offers     the tool opens the screen and answers the five questions:
                 - which grid IS the report (when several look alike, check on screen);
                 - is the period a day or a MONTH;
                 - is there a division - if VD is not in the tree, CHOOSE, never guess;
                 - which result column holds the date, so the day can be PROVEN;
                 - is it a live monitor (no date: a snapshot of now).
  3 Scope      grid, division (default VD), period (default yesterday), the date
               column to verify, options, filters.
  4 Record     "Dry run" applies everything and stops before Inquiry - to check the
               setup. "Record + check" runs it, then the RECORD CHECK:
                 - the screen that opened is the one asked for;
                 - the division was ticked and the screen confirms it;
                 - every filter was applied and read back;
                 - rows came back; every file exists and is not empty;
                 - (when a CSV is asked for) its rows equal the Inquiry rows;
                 - the rows carry the requested date (or why it cannot be checked);
                   for a TYPED month (e.g. fromDt=toDt=202609) the screen must read the
                   month back, and the rows' own dates are counted. When some rows fall
                   outside the month, look at the same month on the G-MES screen; if
                   G-MES itself lists them, press "I checked it on the G-MES screen".
                   That is kept with the exact pattern you saw - a later run whose rows
                   fall outside differently warns again;
                 - every warning, in plain words;
                 - it was remembered;
                 - a BARE replay (the code and nothing else) works and returns the
                   same rows;
                 - it is ready for batches and schedules.
               PASSED / PASSED WITH WARNINGS / FAILED, kept as a certificate in
               data\certificates. A screen is not "recorded" until this has passed.

EVERY DAY - "Reports", "Run & Batch", "Schedules"
  Reports      every screen, its status, last run and record check. Double-click runs
               it (As recorded / Yesterday / Today). "Record check" proves an older
               recording again. "Import recordings" brings recordings from another PC
               or from the project's screens folder.
  Run & Batch  choose several screens; Plan shows what will run and why anything would
               be skipped, before a browser starts; Run runs them one after another in
               ONE browser. "Save as batch" keeps the choice with its date rule.
  Schedules    a saved batch every day / Mon-Fri / chosen days at a time. It runs only
               while you are signed in to Windows (a locked PC is fine); a PC that was
               asleep runs it when it wakes. Prove a new schedule once with "Run now".
  Row export   one Excel per row of a list (Q321KUM00 Detail Inspection: double-click
               the Insp. Result -> popup -> Excel). Resumable; files are staged on this
               PC and only finished, size-checked files go to a network folder.
  History      every run's report and summary; Self-test; Support package (logs and
               settings for help - never passwords).

THE SIDE PANEL
  The button at the bottom of the side panel (or Ctrl+B) narrows it to its icons and
  gives the pages the room; hover an icon to see its name. Press it again to bring the
  names back. The choice is remembered.

YOUR WINDOW - "Appearance"
  Six themes (Light, Dark, Ocean, Graphite, Sand, Midnight), the text font and the
  console font (only fonts on this PC are offered), and the text size (90 - 140 %).
  Every choice applies instantly and is remembered. Drag the gap between any two
  panels - and above the Activity console - to resize them; double-click a gap to put
  it back. Works at any time, even while a task runs.

STOP
  The red Stop (top right, or Esc) stops any work at the next step - a second or two -
  and still writes the report of what was delivered.

THE SAME TOOL ON THE COMMAND LINE (GMES_Workflow.bat)
  When this GMES folder sits inside the project folder, the command-line tool beside it
  (GMES_Workflow.bat, gmes_report.py, gmes_batch.py, gmes_rowexport.py) is the SAME tool
  - same engine, same features, and the same recordings, batches, record checks,
  confirmations and run history. Each one syncs with the other when it starts and after
  every change, so a screen recorded here can be run, checked or batched there at once,
  and the other way round. Nothing is ever deleted by a sync (a replaced or forgotten
  file is kept in the project's screens\.twin\backup). A batch saved differently in both
  is shown as "Not synced" until it is saved again in the right one. Schedules stay
  separate on purpose, so nothing runs twice. Self-test says whether both are level.
  A copy of this folder on another PC works on its own; it has nothing to sync with.

THE WEEKLY HQ REPORTS (MR.Park) - "Weekly reports guide" in the side panel
  The knowledge behind the weekly Tact Time and In-house reports: the manager's e-mails and
  how his rules changed (W38/W39 -> W40), every calculation and target, what was proven
  against his numbers, the defects found in his workbooks, the weekly batch weekly_hq and
  the dashboards it feeds. The same text is WEEKLY_REPORTS.md beside the program.

TWO G-MES: SEEG AND HQ
  The switch at the top of the window (SEEG G-MES | HQ G-MES) chooses which G-MES the
  window works on. HQ G-MES (gmes4, "MES HQ") lists several factories in one tree. Each
  keeps its OWN recordings, batches, record checks and schedules (HQ's are in
  data\sites\hq) - a screen recorded on one is never replayed on the other. A schedule
  made while HQ is chosen runs on HQ (its task name ends in .hq). Your login is the same.

ON A SERVER - make_package.bat server
  1 On the PC where the screens were recorded (the project folder):
      build_exe.bat, then  make_package.bat server
    It makes GMES_Automation_server_package.zip: the program, this file, and seed\ -
    every recording, saved batch and record check of BOTH G-MES, as proven here. A
    batch the window and the command line disagree on is left out, and named.
    A recording pinned to a folder of this PC (D:\..., C:\Users\...) goes without that
    pin - on the server it runs into data\output, or into its batch's folder. A network
    folder (\\server\share\...) is kept.
  2 On the server, signed in as the Windows user that will run the schedules: unzip it
    to a folder of its own (or over the old copy - data\ is never in the zip), start
    Start_GMES.bat. On its first start the window takes everything in seed\ into data\:
    nothing learned on the server is replaced (a recording changed on both goes to the
    newer one, the other kept in seed\screens\.twin\backup; a batch saved differently on
    both is shown as "Not synced" and left alone). History > Self-test shows it.
  3 Account & Browser: save the login of THAT Windows user, "Test sign-in" once.
  4 Choose HQ G-MES at the top, then Schedules: schedule the batch (e.g. weekly_hq every
    Monday 10:00) and prove it once with "Run now".
  5 Then remove the same schedule from the PC it ran on before
    (python gmes_batch.py --site hq unschedule weekly_hq) - two PCs would deliver the
    same files twice; the tool can only stop a double schedule on ONE PC.
  A schedule runs only while its Windows user is signed in (a disconnected remote
  session counts as signed in; signing OUT does not).

WHERE THINGS ARE (inside this folder)
  data\screens        recordings made here          data\output   exported files
  data\logs           logs, run reports (batches)   data\certificates  record checks
  data\schedules      the launchers Task Scheduler runs
  data\diagnostics    a screenshot whenever something failed

GOOD TO KNOW (learned the hard way - see HISTORY.md in the project)
  - Almost every failure here produced NO error: a click on empty space, the wrong day,
    the wrong division. That is why every run proves the screen, division, rows, date
    and file, and why a recording must pass its record check.
  - The .xlsx files are encrypted by Samsung DRM. The rows are checked against G-MES's own
    data BEFORE the file is written; choose 'CSV only' when a readable file is needed.
  - A date "remembered" by a recording goes stale - for daily reports use the batch's
    date rule (Yesterday / Today), not "As recorded".
  - Do not click inside the automation browser or sort a grid while it works.
  - One browser for the whole app: starting it costs a sign-in, so it stays open until
    the app closes.

SUPPORT
  GMES_Automation.exe --selftest       login, browsers, recordings (no sign-in)
  GMES_Automation.exe --batch NAME     run a saved batch without a window
  build_exe.bat / make_package.bat     rebuild the .exe / make the zip to hand on
