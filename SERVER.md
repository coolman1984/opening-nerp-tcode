# Running the G-MES tool on a server

The tool runs batches by itself through Windows Task Scheduler. On a server that works
exactly as on a desk PC - **as long as the rules below are kept.** Every rule here is a
way a night run has failed, or would fail, without saying so at the time.

## Move it

On the PC the tool runs on now:

```bat
GMES_Workflow.bat package
```

This makes `dist\GMES_Tool_<time>\` and the same as a `.zip`: every file the tool needs
(found by following its imports, so nothing can be forgotten), your recordings, saved
batches, record checks, and the list of your schedules - and nothing else. It never
contains your saved sign-in or the browser profile: both are bound to one Windows user on
one PC and cannot work anywhere else. The zip holds production data (filter values,
folder names): move it like any work file, never through git.

On the server:

1. Unzip it to a **short local folder**, e.g. `C:\gmes`. Not OneDrive, not the Desktop, not
   a network drive (a long path breaks exports; a sync client locks fresh files). If the
   zip came by e-mail or download, open its Properties and tick **Unblock** first, or
   Windows may ask "Do you want to run this file?" every time `GMES_Workflow.bat` starts.
   (Schedules are not affected: their launchers are written on the server by `setup`.)
2. Install **Python 3.10+ from python.org** - not the Microsoft Store one, which a scheduled
   task cannot always start - then once: `python -m pip install -r requirements.txt`.
3. `GMES_Workflow.bat verify` - every file arrived, unchanged (SHA-256 against
   `MANIFEST.json`).
4. `GMES_Workflow.bat setup` - signed in as the Windows user the batches will run as. It
   runs the readiness check, asks for that user's G-MES sign-in, and offers to create the
   schedules the package came with. It asks before every change.
5. Prove one schedule while you watch: `python gmes_batch.py run-scheduled <batch>`, then
   `python gmes_batch.py schedules` (last result) and `logs\batches\latest_summary.html`.

## The rules a server must keep

| Rule | Why | Checked by `GMES_Workflow.bat server` |
|---|---|---|
| **The schedules' Windows user stays signed in.** Lock it, or close a remote desktop window / Disconnect. **Never "Sign out".** | The saved sign-in (DPAPI) and the browser both need that user's session; the tasks are "run only when the user is logged on". Signed out, nothing runs - and nothing says so until the morning. | reminds you |
| **After a restart, someone signs in - or Windows does it.** | Windows Update restarts servers at night. Until the user signs in again, no schedule runs. Ask IT for automatic sign-in of the account, or check after every restart. | WARN when automatic sign-in is off |
| **The server does not sleep.** | A sleeping PC runs a batch when it wakes, not at its time. `powercfg /change standby-timeout-ac 0` | WARN when it sleeps |
| **Every folder a report saves to exists on the server and this account can write to it.** | A report's folder is remembered with the report. `C:\Users\<someone>\Downloads` exists on one PC only; a network folder the server's account may not write to fails after the query. | FAIL with the screens that use it |
| **Schedules are created on the server, from the server's folder.** | A task stores the full path of the tool it runs. A task made on the old PC, or before the folder was moved, runs the old copy - or nothing. | FAIL "runs the copy in ..." |
| **One copy of the tool schedules a batch.** | Two copies (or this tool and GMES Automation on the same PC) would export it twice and fight over the browser. | setup refuses to double a schedule |
| **The server's clock is right.** | "Yesterday" comes from the clock; a batch refuses to run when it is more than 15 minutes from G-MES's. | at every run |
| **Do not use the automation browser yourself, and do not run anything else in it.** | One run at a time drives one browser; a second waits (exit 3) and is retried twice, 15 minutes apart. | at every run |

## Folders from the old PC

```bat
GMES_Workflow.bat move-folder "C:\Users\m.labib\Downloads" "D:\GMES\Reports"
```

Every recording and batch that saved to the old folder (or a folder inside it) saves to
the new one. It shows the change first, checks that the new folder can be written, asks,
and keeps the files as they were in `screens\.backup\`.

## Every night, and when something went wrong

- `GMES_Workflow.bat server` - the whole check again; changes nothing in G-MES or the tool
  (it writes and at once deletes a tiny test file in each output folder; `--no-write-test`
  skips that).
- `python gmes_batch.py schedules` - each schedule, when it runs next, how it last ended.
- `logs\batches\latest_summary.html` - the last batch: what was delivered, what was not and
  why, a screenshot of each failure. `logs\scheduled_<batch>.log` - the launcher's lines.
- Exit codes: 0 ok, 1 some screens failed, 3 another run held the browser (retried), 4
  sign-in failed (retried; many sign-ins in a short time can stop the Samsung sign-in
  window for a while - do not force it), 9 the launcher could not find the tool (moved).

## Moving it again

`GMES_Workflow.bat package` works on the server too: it packages that copy, its recordings
and its schedules. Delete the old copy's schedules (`python gmes_batch.py unschedule
<batch>`) on the machine you leave, so a batch is not run twice.

## Not established

Running the schedules "whether the user is logged on or not" (no signed-in session) is not
supported and has never been tried: the saved sign-in and the browser are both tied to a
signed-in session. Keep the user signed in.
