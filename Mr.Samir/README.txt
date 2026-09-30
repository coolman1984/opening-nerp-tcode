SAMIR EXPORT - G-MES "Detail Inspection" (Q321KUM00), one Excel file per row
==========================================================================

WHAT IT DOES
  For every row of the Detail Inspection list whose Insp. Result is a link
  (PASS), it does what you did by hand:
    1. double-click the word PASS          -> the detail popup (Q321KUP00) opens
    2. click the Excel icon in the popup   -> the "Save to Excel" box opens
    3. tick grdPackInspArtList only (and "save a single file"), press OK
    4. save the .xlsx under its own name    <plan date>_<model>_<lot no>.xlsx
  It then goes on to the next row. It does not change anything in G-MES.

HOW TO START
  Double-click  Start_Samir.bat   (it opens SamirExport.exe; without the .exe it
  uses Python). Nothing else has to be installed to use the .exe.
  The first time, it asks for YOUR Knox / G-MES login once. The login is
  encrypted with your own Windows account and cannot be read by anyone else or
  on another PC. It is never written to a log or to any file of this folder.

THE THREE STEPS IN THE WINDOW
  1. Filters      Division (default MAIN Part), Monthly or Daily, and the period.
                  Leave the period EMPTY to use the current month (or today):
                  in October it follows October by itself. Type 202609 to force
                  a month, or 20260930 for a day (Daily).
                  "Extra filters": Name=Value; Name=Value  (e.g. Model=UA65M70).
                  Press "Connect and load rows". It shows how many rows G-MES
                  found and how many can be exported (e.g. PASS 1068 of 1074).
  2. What to export
                  Result grid, the column and the text that are clicked, and
                  which grids to save in the Excel box. Every grid you do not
                  list is UNticked. Several grids need "single file = Yes".
                  File name pattern uses {plan} {model} {lot}. A file is never
                  overwritten (a second one gets -2, -3, ...).
  3. How many     "Start at row No." and "Number of rows" (0 = all the rest).
                  Try 5 first. Then START. The counter shows done / ok / skipped
                  / failed and the time left.

STOPPING
  STOP           stops after the click in progress (a second or two), closes any
                 open popup and leaves no half-written file. The run list says
                 which row was open.
  STOP NOW       also closes the automation browser at once (the last resort).
  Pause / Resume holds the run between clicks.
  On error       "stop" (default) stops at the first row that fails after one
                 retry; "skip" carries on and stops after 3 failures in a row.

RESUMING / RUNNING AGAIN
  "Skip rows whose file already exists" is on by default: run it again with the
  same folder and only the missing rows are done. Rows are matched by file name
  (the default name contains the lot number, which is unique).

WHERE THINGS ARE (all inside this folder, next to the .exe)
  data\output\<screen>_<period>\   the Excel files and results_<time>.csv
                                   (row, plan, model, lot, ok/skipped/failed/
                                   stopped, file, bytes, seconds, note)
  data\logs\                       the log of each day
  data\diagnostics\                a screenshot of any row that failed
  data\settings.json               your last settings (no password)

WHAT IT CHECKS FOR YOU
  - before a click: the row shown in the grid is the row the data says it is
    (model + plan date); if the grid was sorted or changed, it stops.
  - the popup that opens shows the same model and plan date;
  - the box really has only the grids you chose ticked before OK;
  - the file arrived, is not empty, and has a name of its own;
  - free disk space; the folder can be written to; the browser is still there.
  The .xlsx files are encrypted by Samsung DRM: nothing here opens or reads them.

LIMITS - READ THESE
  - Speed: about 6 seconds per row on a normal day (1,068 rows is about 2 hours);
    G-MES is sometimes slower and some rows take 14 seconds.
  - Keep G-MES itself alone while it runs: do not click inside the automation
    browser window and do not sort its grid. Work in other windows as you like.
  - It needs Chrome or Edge on the PC and your network access to G-MES.
  - Only PASS-type rows have a link; other rows (In progress, Outgoing Revoke,
    blank) are counted and left alone.
  - A flat "Weekly" period is not offered (never tested).
  - Sign in only as often as you need: many sign-ins in a short time can stop
    the Samsung sign-in window from opening. The program reuses an open session.

REBUILDING THE .EXE (only if the sources change)   build_exe.bat
  It refreshes app\engine from the project's engine modules (identical copies,
  checked by tests), runs the tests, then builds SamirExport.exe with PyInstaller.
  Support: SamirExport.exe --selftest   and   SamirExport.exe --cli --rows 5
  (--cli runs the same program without a window; output in data\logs\console.txt).
