SAMIR EXPORT 2.0 - G-MES "Detail Inspection" (Q321KUM00), one Excel file per row
===============================================================================

WHAT IT DOES
  For EVERY row of the Detail Inspection list (PASS, In progress, Outgoing Revoke,
  anything in Insp. Result) it does what you would do by hand:
    1. double-click its Insp. Result           -> the detail popup (Q321KUP00) opens
    2. click the Excel icon in the popup    -> the "Save to Excel" box opens
    3. tick only the grids you chose, press OK
    4. save the .xlsx under its own name     <plan date>_<model>_<lot no>.xlsx
  then the next row. It never changes anything in G-MES - it only reads and downloads.

START
  Double-click  Start_Samir.bat   (it opens SamirExport.exe; nothing has to be
  installed for the .exe). Chrome or Edge must be on the PC.

FIRST TIME ON A NEW LAPTOP - the "Account & Browser" tab
  "This PC" shows four checks: G-MES login, Chrome / Edge, Browser copy, Output folder.

  A. G-MES login   Type the person's own Knox / G-MES user ID and password (twice),
                   press "Save login". It is encrypted with Windows for THAT Windows
                   account on THAT PC only - nobody else and no other PC can read it,
                   and it is never shown or written to any log. Each person saves their
                   own login on their own laptop. "Test sign-in" checks it once.
  B. Browser       "Automatic" uses the Windows default browser (recommended), or pick
                   Chrome / Edge and press "Use this browser". On the first Connect the
                   tool makes its OWN copy of that browser's profile, once, so a G-MES
                   session the person already has comes along. Their own browser is
                   only read: never changed, never controlled, never deleted.
                   If that browser is open during this first copy, the tool says so:
                   close its windows once and press Connect again.

EVERY DAY - the "Export" tab
  1 Filters      Organization (default MAIN Part), Monthly or Daily, and the period:
                 "This month" / "Last month" (or Today / Yesterday) follow the calendar
                 by themselves - in October "This month" is October. "Choose..." takes
                 a fixed month (2026-09) or day (2026-09-29). Model and SN No. optional.
  Run            "Connect & load rows": signs in (or reuses the open session), opens
                 the screen, applies the filters, presses Inquiry. The tiles show how
                 many rows G-MES found and how many can be exported.
  2 Rows         Start at row No. and How many (quick buttons 5 / 20 / 100 / 500, or
                 "All remaining rows"). The line below says exactly which rows, how
                 many files, and about how long.
  3 Excel files  Which grids to tick in "Save to Excel" (grid 1 only by default), save
                 as a single file, the file name, "skip rows whose file already exists"
                 (resume), and the folder.
  Start export   A confirmation shows rows, folder and time; then the tiles count
                 Exported / Skipped / Failed and the time left.
  Advanced       (Show) result grid, the column and text that are double-clicked, more
                 grids, more filters, what to do when a row fails, retries, a pause.

STOPPING
  Stop  (or Esc)   stops after the click in progress (a second or two), closes any open
                   popup, leaves no half-written file. The result list says which row
                   was open.
  Pause / Resume   holds the run between rows.
  Force stop + close browser   the last resort: also closes the automation browser.

WHERE THINGS ARE (inside this folder, next to the .exe)
  data\output\<screen>_<period>\   the Excel files + results_<time>.csv
                                   (row, plan, model, lot, ok/skipped/failed/stopped,
                                   file, bytes, seconds, note)
  data\logs\                       the activity log of each day
  data\diagnostics\                a screenshot of any row that failed
  data\settings.json               your last choices (never the password)

WHAT IT CHECKS FOR YOU
  - before a click: the grid row is the row the data says it is (model + plan date);
    if the grid was sorted or changed, it stops;
  - the popup that opens shows the same model and plan date;
  - before OK: only the chosen grids are ticked in the Save to Excel box;
  - the file arrived, is not empty, and gets a name of its own (never overwrites);
  - free disk space; the folder can be written to; the browser is still there.
  The .xlsx files are encrypted by Samsung DRM: nothing here opens or reads them.

LIMITS - READ THESE
  - About 5-7 seconds per row (1,068 rows is about 2 hours); some rows take 14 s.
  - Do not click inside the automation browser or sort its grid while it runs. Working
    in other windows is fine; it kept working with the PC locked, too.
  - Every status is exported by default (Advanced > 'Only rows showing' narrows it).
    If someone clicks a column header in G-MES the list is SORTED and row numbers
    follow that order - the log says so. Weekly periods are not offered.
  - Sign in only as often as needed: many sign-ins in a short time can stop the
    Samsung sign-in window from opening. The tool reuses an open session.

SUPPORT
  SamirExport.exe --selftest      checks login, browsers, engine (no sign-in)
  SamirExport.exe --cli --rows 5  the same program without a window
                                  (its output goes to data\logs\console.txt)
  build_exe.bat                   rebuild the .exe after a source change (runs the tests)
  make_package.bat                makes Mr.Samir_package.zip to hand to another person
