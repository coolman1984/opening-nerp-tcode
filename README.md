# G-MES automation

[![Offline test suites](https://github.com/coolman1984/opening-nerp-tcode/actions/workflows/tests.yml/badge.svg)](https://github.com/coolman1984/opening-nerp-tcode/actions/workflows/tests.yml)

Windows automation for **Samsung G-MES**, a Nexacro manufacturing execution
system, driven through the Chrome DevTools Protocol. It signs in unattended
with a DPAPI-stored credential, opens any screen the account can reach, sets
that screen's filters, runs its Inquiry, verifies what came back, and exports
it as G-MES's own Excel download. Excel only, since HISTORY.md Phase 98.1;
a CSV copy from the data layer is still available with `--export csv`.

It works against a **live production system**. Read [CLAUDE.md](CLAUDE.md)
before changing anything, and [HISTORY.md](HISTORY.md) before changing
automation behaviour — almost every failure this project has hit produced no
error at all, and the causes are rarely guessable from the code.

> **About the name.** The repository is called `opening-nerp-tcode` because it
> began as an N-ERP (SAP) T-code opener. N-ERP was removed in HISTORY.md
> Phase 72 and this is a G-MES-only project now; the name is historical. The
> N-ERP code is on branch `archive/nerp-before-removal`.

## Setup — on any PC

```powershell
python -m pip install -r requirements.txt   # websocket-client, and nothing else
python gmes_credentials.py set              # once per person, into their own DPAPI store
.\GMES_Workflow.bat                         # first run: builds its profile, signs in once
```

That is the whole install. Python 3.12 on PATH; Chrome is located
automatically (`CHROME_PATH` overrides). The only third-party dependency is
`websocket-client` — deliberately, because this runs in a locked-down
corporate environment.

**What happens on a new machine.** The tool gives itself a browser profile at
`%LOCALAPPDATA%\GMES_Automation\profiles\default`. On the **first run only**, it
builds that profile by copying the one you already use — Chrome or Edge,
whichever Windows has as your default browser — so the G-MES session you are
already signed in with can come across. **That is the intent, not a promise:** on\nthe one clean-machine rehearsal (HISTORY.md Phase 84.10) the copy completed but the\nsession did not sign in by itself - the first sign-in went through SSO with the saved\ncredentials, after one automatic retry.

That copy happens **once**, on this PC, and the rules around it are strict:

- Your real browser profile is only ever **read**. It is never launched, never
  debugged, never modified and never deleted.
- Because the browser keeps its cookie database locked while it runs, the first\n  run may ask you to close that browser once (on the rehearsal it did not, and the\n  copy finished with Chrome open). Every run after it does not care whether your\n  browser is open.
- Nothing is copied again afterwards. A second copy would overwrite the G-MES
  session the automation has since built up.
- If there is no Chrome or Edge profile to start from, the profile is created
  empty instead and the first sign-in is a real one — which is exactly how the
  tool behaved before, and still a fully working path.
- Prefer not to have your profile copied at all? Set `GMES_BOOTSTRAP=off` and
  you get the empty profile and a single real sign-in.

`python gmes_browsers.py` prints what it can see — your default browser, both
browsers' profiles, and what the first run recorded — and changes nothing.

Nothing carries a session between machines, and nothing can: Chrome 140+ binds
cookie encryption to the machine it is running on, so a copied profile cannot
decrypt its own cookies elsewhere. Each person signs in once, as themselves,
with their own credentials in their own DPAPI store.

What *does* travel with the tool is everything it has learned about the
screens — see `screens_known/` below — so a known screen works on day one
without anyone re-teaching it.

| Where | What | Shared? |
|---|---|---|
| `%LOCALAPPDATA%\GMES_Automation\credentials.dat` | Knox ID + password, DPAPI | Never — per Windows account |
| `%LOCALAPPDATA%\GMES_Automation\profiles\` | the tool's own browser profile | Never — machine-bound |
| `%LOCALAPPDATA%\GMES_Automation\browser.json` | which browser/profile the first run chose | Never — names the machine it was built on |
| `screens_known/` | screen structure: fields, grids, trees | **Yes — committed** |
| `screens/` | what your runs used: division, dates, values | Never — git-ignored |

## Running a report

`GMES_Workflow.bat` is the entrance. With no arguments it asks questions; with
arguments it runs a report directly.

```powershell
.\GMES_Workflow.bat                                     # guided, interactive
.\GMES_Workflow.bat P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
.\GMES_Workflow.bat record P1112UM00 --division VD --date 20260909 --verify planYmd
.\GMES_Workflow.bat check P1112UM00                     # also: status, confirm, forget, find, describe
.\GMES_Workflow.bat rowexport --period previous         # one Excel per row of Q321KUM00
.\GMES_Workflow.bat sync                                # level with GMES Automation (also: parity)
```

In the menu, **Esc goes back one step** - one question, one list, one level - and only
Esc at Home exits; **Ctrl+C stops what is running and comes back Home**. In a typed
answer the first Esc clears it, the second goes back.

**Do not type `run` after `GMES_Workflow.bat`** — the launcher adds it. Typing
it twice makes the tool search for a screen called `RUN`. The word is only
needed when calling the CLI directly:

```powershell
python gmes_report.py run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
python gmes_report.py describe P1112UM00      # what filters, grids and options a screen has
python gmes_report.py find "production plan"  # search the screen catalogue
python gmes_open_screen.py --find production
python gmes_data.py forms                     # which screens are open, and their datasets
```

A date-constrained run **requires** `--verify COLUMN`, because an export of
the wrong day looks exactly like an export of the right one.

### Record a screen and prove it

```powershell
python gmes_report.py record P1112UM00 --division VD --date 20261006 --verify planYmd
python gmes_report.py check P1112UM00 R3220UM00   # prove earlier recordings again
python gmes_report.py status                      # every recording + its last record check (offline)
python gmes_report.py confirm Q321KUM00           # a typed period G-MES itself defines (offline)
python gmes_report.py forget P1112UM00            # asks first; a copy is kept
```

`record` runs the screen, replays it **bare** (the code and nothing else), asks the
batch planner, judges every item (screen, division, filters, rows, files, date,
remembered, replay, batch-ready) and keeps a certificate: PASSED / PASSED WITH
WARNINGS / FAILED. A 6-digit `--from/--to` is a whole month. It is the same code as
GMES Automation's "Record + check", and both show the same certificates.

### Row export: one Excel per row of a list

```powershell
python gmes_rowexport.py --load-only --period previous     # open, Inquiry, count
python gmes_rowexport.py --period previous                 # every row of last month
python gmes_rowexport.py --period 202609 --start-row 120   # resume from row 120
```

Q321KUM00 Detail Inspection by default (double-click the Insp. Result -> popup ->
Excel). Files already in the folder are skipped, so a stopped run resumes. Also on
the `GMES_Workflow.bat` Home menu (9).

## Connecting an AI agent (MCP)

An AI agent can drive the tool without reading its code, through **`gmes_mcp.py`**, an MCP
server over this same command line (HISTORY.md Phase 129). Every tool runs an existing
command, so every refusal, lock and check is the command line's own.

| Client | How |
|---|---|
| Claude Code, in this folder | already configured by `.mcp.json` - approve `gmes` once (`/mcp`) |
| Claude Code, any folder | `claude mcp add --scope user gmes -- python "<this folder>\gmes_mcp.py"` |
| Codex CLI | `codex mcp add gmes -- python "<this folder>\gmes_mcp.py"`, then `tool_timeout_sec = 5400` under `[mcp_servers.gmes]` in `%USERPROFILE%\.codex\config.toml` |
| Claude Desktop, Cursor, VS Code, Gemini CLI | `python gmes_mcp.py config` prints the exact entry for each |
| An agent with only a shell | `python gmes_mcp.py tools`, then `python gmes_mcp.py call status` / `call batch_plan --args-file plan.json` |

**The tools (first release):** offline - `status`, `batch_list`, `batch_plan`, `batches`,
`schedules`, `recent_batch_report`, `twin_status`, `preflight`; live (signs in, read-only in
G-MES) - `find_screen`, `describe_screen`, `run_report`; and `close_browser`. Recording,
batch runs, row export and schedules stay on the command line for now.

What the server enforces, whatever the agent does:
- one call at a time (a second waits up to 2 minutes, then is refused as busy);
- `run_report` asks for `confirm: true` before anything that changes what a recorded screen's
  later replays and scheduled batches do (another scope, a pinned folder or export, relearn);
- a run is ok only when the command succeeded, its own result says ok, and every file it names
  exists with a size;
- a call past its limit (10 minutes offline, 90 live), cancelled, or left by a closed client is
  stopped; the browser is closed only if this server started it;
- no credentials, no free commands, and every answer is passed through the secret redaction.

**Why no HTTP server:** every agent tried here launches a local MCP server itself, and the
GMES Automation window already has its own local page. An HTTP endpoint would be a network
service on a corporate PC that holds a signed-in G-MES session - more to secure, nothing an
agent here needs. Revisit only for an agent that cannot start a local program.

## Moving the tool to a server

```powershell
.\GMES_Workflow.bat package       # here: dist\GMES_Tool_<time>\ + .zip - the tool, recordings, batches, schedules
.\GMES_Workflow.bat verify        # there: every file arrived unchanged (MANIFEST.json)
.\GMES_Workflow.bat setup         # there: the check, your sign-in, the same schedules (asks first)
.\GMES_Workflow.bat server        # any time: is this PC ready to run the batches by itself?
```

Read [SERVER.md](SERVER.md) first: a schedule runs only while its Windows user is signed
in, and every folder a report saves to must exist on the server - `move-folder` re-points
the ones that do not. `.\GMES_Workflow.bat help` lists every command on one screen.

## Two front ends, one tool: the command line and GMES Automation

`GMES_Workflow.bat` (this command line) and `GMES\GMES_Automation.exe` (a window for
people who do not use a terminal, [GMES/README.txt](GMES/README.txt)) are **always at
the same level** (CLAUDE.md section 0a):

- **Same engine** - the window carries byte-identical copies of these modules.
- **Same features** - `python gmes_twin.py parity` lists every window feature and the
  command for it here; a test fails if the window gains one the command line lacks.
- **Same recordings, batches, record checks, confirmations and run history** - each
  syncs with the other on start and after every change (`screens\` <->
  `GMES\data\`). `python gmes_twin.py status` shows what differs; `sync` levels them.
  Nothing is ever deleted - a replaced or forgotten file goes to
  `screens\.twin\backup\`. A batch saved differently in both is reported, not merged.
- **Schedules stay separate** on purpose (`GMES_Batch_*` / `GMES_App_*`), so a batch
  never runs twice.

## Setting up a new PC

1. **Install under a short folder**, for example `C:\gmes` - not a OneDrive or
   Documents path. A deep path breaks `git clone` (unless
   `git config --global core.longpaths true`), Windows' 259-character file limit, and a
   sync client holds fresh exports open. Clone with `git clone <repo> C:\gmes`.
2. **Python 3.10+ from python.org** (a Microsoft-Store Python may not start from a
   scheduled task), then `python -m pip install -r requirements.txt`.
3. **`python gmes_preflight.py`** - read-only. `FAIL` lines must be fixed (for example a
   `RemoteDebuggingAllowed=0` browser policy needs IT); `WARN` lines are worth reading
   (path length, cloud-sync folder, no saved sign-in yet).
4. **`python gmes_credentials.py set`** once, as the Windows user who will run it. The
   sign-in is stored encrypted for that user only; if their Windows password is ever
   *reset* (not changed), the tool says it cannot decrypt the file and asks for it again.
5. **The first run is slow and may ask twice.** A new browser profile has no cache, so
   the first sign-in and the first open of each screen take much longer; the first
   sign-in attempt can fail once ("SSO window never opened") and is retried
   automatically. Do not sign in over and over to test it - after a handful of
   sign-ins in a short time the SSO window stopped opening for a while.
6. Record a screen once (`GMES_Workflow.bat`), replay it, then use Batch. See
   [PROJECT_EXPERIENCE.md](PROJECT_EXPERIENCE.md) section 18 (recording) and 23 (a new PC).

## Batch runs

Replay several recorded screens together - all of them, a chosen few, or a
saved list - now or on a schedule. Answer **B** (Batch) in `GMES_Workflow.bat`,
or use the command line:

```powershell
python gmes_batch.py list                          # what is recorded, numbered
python gmes_batch.py plan all                      # what WOULD run; no browser, nothing touched
python gmes_batch.py run all                       # everything, for yesterday
python gmes_batch.py run 1,3,5-7 --date today      # a chosen few
python gmes_batch.py run all !Q2111UM00            # everything except one
python gmes_batch.py save morning 1,3,5-7          # save a list
python gmes_batch.py run --batch morning           # run a saved list
python gmes_batch.py schedule morning --at 06:30 --weekdays
python gmes_batch.py schedules                     # what is scheduled, next run, last result
python gmes_batch.py unschedule morning
```

- `run` needs an explicit selection - it never means "everything" by itself.
- Dates: `yesterday` (default), `today`, `-3`, `20260915`, `20260901:20260907`,
  or `keep` (each screen's own remembered dates). They are applied to every
  screen. A screen that cannot be run safely (not recorded here, or a date with
  no column to verify it against) is listed as **skipped** with the reason.
- One screen failing does not cancel the rest; three failures in a row, or a
  session that cannot be recovered, stop the batch. Files go to a
  `Data Hub Folder\GMES\batch_<time>` folder and a report to `logs\batches\`.
- The morning after, open `logs\batches\latest_summary.html`: what was
  delivered, what was not and why, with a screenshot of each failure.
- A batch whose dates come from the PC's clock (`yesterday`, `today`, `-N`)
  first compares that clock with the G-MES server's; if they are more than
  15 minutes apart it runs nothing and says so.
- Exit code: 0 all ok, 1 something failed, 2 usage, 3 another run holds the
  browser, 4 sign-in failed.
- In PowerShell a saved list is written `'@morning'` in quotes (a bare `@name`
  means something else there), or use `--batch morning`.
- **A schedule runs only while you are signed in to Windows** - the saved
  credentials and the browser need your session. A PC asleep at the time runs
  it on waking. Follow a run in `logs\scheduled_<name>.log`.

### Team folders (the DataHub share)

A screen can deliver its Excel to one or more team folders on
`\\106.139.69.145\DataHub Shared Folder\<department>\...` on top of the local
copy. The list is the screen's own `distribute_to` (in its git-ignored profile);
set or replace it with `--distribute-to "<folder>"` (repeat the flag) on a run,
and it is then applied by every later replay, batch and schedule
(HISTORY.md Phases 91-93). A copy of a DRM Excel is blocked, so each extra
folder gets a fresh download. One folder failing is a warning, never a failed
run. Confirm a delivery on the share itself, not from the log.

### Which day a report is for

A batch has **one** date policy for all its screens. There is no `+N` (D+1)
policy and no per-screen offset yet - reports that need "today" or D+1 belong
in their own saved group until one is built (HISTORY.md Open Item 93). A
screen's remembered dates and months (`fromDate`, `mskFromDate`, `startYm`...)
follow the policy; screens with no date (live snapshots) ignore it. Some
periods are a production day, not a calendar day (`R5222WM04`, `L5323UM00`:
about 08:00 to 08:00), so their rows are typed, not row-verified.

## Everyday commands

| Task | Command |
|---|---|
| Guided run | `.\GMES_Workflow.bat` |
| Describe a screen | `python gmes_report.py describe <CODE>` |
| Set up filters without querying | `... run <CODE> ... --dry-run` |
| Nightly Production Plan export | `python gmes_daily_prodplan.py` |
| Run several recorded screens | `.\GMES_Workflow.bat`, choose **3. Run several reports** from the main menu |
| Find a saved report, see if it is ready and how it last went | `.\GMES_Workflow.bat`, **4. Saved reports** - type words to search |
| Record a screen and prove it (bare replay, judged, certificate) | `python gmes_report.py record <CODE> ...` |
| Prove a recording again | `python gmes_report.py check <CODE>`, or **4. Saved reports** -> Record check |
| One Excel per row of a list | `python gmes_rowexport.py`, or **9. Row export** |
| Is the command line level with GMES Automation? | `python gmes_twin.py status` |
| Find the files of an earlier run, open its folder | `.\GMES_Workflow.bat`, **6. Recent runs and files** |
| Run every recording | `python gmes_batch.py run all` |
| Run a chosen few | `python gmes_batch.py run 1,3,5-7` |
| Schedule a saved list | `python gmes_batch.py schedule morning --at 06:30 --daily` |
| Read a dataset | `python gmes_data.py read <CODE> <dataset>` |
| What is on screen right now | `python gmes_inspect.py` |
| Live demo, three screens | `.\Demo_ForManagement.ps1` |

## Architecture

One engine: the flat modules at the repository root — `gmes_core.py` (the
screen driver), `gmes_login.py`, `gmes_common.py`, `gmes_open_screen.py`,
`gmes_data.py`, `gmes_profile.py`, over the `cdp_common.py` transport.
[ARCHITECTURE.md](ARCHITECTURE.md) has the full map.

Both `GMES_Workflow.bat` branches reach those modules and nothing else, which
`tests/test_legacy_entrance.py` proves in a fresh interpreter. A `src/gmes`
package was tried and removed in Phase 57; see
[docs/history/CAPABILITY_RESCUE_MAP.md](docs/history/CAPABILITY_RESCUE_MAP.md)
for what it taught and what was kept.

## Tests

Seven offline suites. None needs a browser or a network, and all must stay green.

```powershell
python tests/test_cdp_common.py
python tests/test_gmes_core.py
python tests/test_legacy_hardening.py
python tests/test_gmes_workflow.py
python tests/test_legacy_entrance.py
python tests/test_project_eye.py
python tests/test_browser_bootstrap.py
```

There is no mock for G-MES, by design — it sits behind corporate SSO and the
failures worth catching are live ones. A green suite guards decision logic; it
is **not** evidence that a run works. **No test command above is authorization
to use a live authenticated portal.**

## Documentation

| File | What it is |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Operating rules. Read first. |
| [GMES_SKILL.md](GMES_SKILL.md) | 106 numbered G-MES gotchas, each earned live |
| [HISTORY.md](HISTORY.md) | Every incident, cause and fix — keep it updated |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module map and where runtime state lives |
| [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) | How an AI agent records, replays and batches any UI number |
| [PROJECT_EXPERIENCE.md](PROJECT_EXPERIENCE.md) | The fast mental model for a newcomer |
| [HOW_TO_USE.md](HOW_TO_USE.md) | Usage guide (Arabic) |
| [docs/history/](docs/history/) | Kept for their reasoning, not their accuracy |

## Safety

Credentials live only in the DPAPI store at
`%LOCALAPPDATA%\GMES_Automation\credentials.dat` — never in source, arguments,
logs or commits. `%LOCALAPPDATA%\GMES\credentials.dat` belonged to the removed
package and is equally protected; no migration or inspection of either is
authorized.

The automation drives a profile of its own and never the user's real one. That
profile is built once, by reading the real one; from then on the real profile
is not touched at all, and no code path anywhere launches, debugs, modifies or
deletes it. Every G-MES operation is read-only: it sets filters and runs
queries, and has no code path that saves, submits, approves or deletes anything
in G-MES.
Exported data, run logs and learned screen profiles are all git-ignored and
must stay that way.
