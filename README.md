# G-MES automation

Windows automation for **Samsung G-MES**, a Nexacro manufacturing execution
system, driven through the Chrome DevTools Protocol. It signs in unattended
with a DPAPI-stored credential, opens any screen the account can reach, sets
that screen's filters, runs its Inquiry, verifies what came back, and exports
it — as G-MES's own Excel download and as a CSV read from the data layer.

It works against a **live production system**. Read [CLAUDE.md](CLAUDE.md)
before changing anything, and [HISTORY.md](HISTORY.md) before changing
automation behaviour — almost every failure this project has hit produced no
error at all, and the causes are rarely guessable from the code.

> **About the name.** The repository is called `opening-nerp-tcode` because it
> began as an N-ERP (SAP) T-code opener. N-ERP was removed in HISTORY.md
> Phase 72 and this is a G-MES-only project now; the name is historical. The
> N-ERP code is on branch `archive/nerp-before-removal`.

## Setup

```powershell
python -m pip install -r requirements.txt   # websocket-client, and nothing else
python gmes_credentials.py set              # once per machine, into the DPAPI store
```

Python 3.12 on PATH. Chrome is located automatically; set `CHROME_PATH` to
override. The only third-party dependency is `websocket-client` — deliberately,
because this runs in a locked-down corporate environment.

## Running a report

`GMES_Workflow.bat` is the entrance. With no arguments it asks questions; with
arguments it runs a report directly.

```powershell
.\GMES_Workflow.bat                                     # guided, interactive
.\GMES_Workflow.bat P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
```

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

## Everyday commands

| Task | Command |
|---|---|
| Guided run | `.\GMES_Workflow.bat` |
| Describe a screen | `python gmes_report.py describe <CODE>` |
| Set up filters without querying | `... run <CODE> ... --dry-run` |
| Nightly Production Plan export | `python gmes_daily_prodplan.py` |
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

Six offline suites. None needs a browser or a network, and all must stay green.

```powershell
python tests/test_cdp_common.py
python tests/test_gmes_core.py
python tests/test_legacy_hardening.py
python tests/test_gmes_workflow.py
python tests/test_legacy_entrance.py
python tests/test_project_eye.py
```

There is no mock for G-MES, by design — it sits behind corporate SSO and the
failures worth catching are live ones. A green suite guards decision logic; it
is **not** evidence that a run works. **No test command above is authorization
to use a live authenticated portal.**

## Documentation

| File | What it is |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Operating rules. Read first. |
| [GMES_SKILL.md](GMES_SKILL.md) | 52 numbered G-MES gotchas, each earned live |
| [HISTORY.md](HISTORY.md) | Every incident, cause and fix — keep it updated |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module map and where runtime state lives |
| [PROJECT_EXPERIENCE.md](PROJECT_EXPERIENCE.md) | The fast mental model for a newcomer |
| [HOW_TO_USE.md](HOW_TO_USE.md) | Usage guide (Arabic) |
| [docs/history/](docs/history/) | Kept for their reasoning, not their accuracy |

## Safety

Credentials live only in the DPAPI store at
`%LOCALAPPDATA%\GMES_Automation\credentials.dat` — never in source, arguments,
logs or commits. `%LOCALAPPDATA%\GMES\credentials.dat` belonged to the removed
package and is equally protected; no migration or inspection of either is
authorized.

The automation drives a **copy** of the user's Chrome profile and never the
real one. Every operation is read-only: it sets filters and runs queries, and
has no code path that saves, submits, approves or deletes anything in G-MES.
Exported data, run logs and learned screen profiles are all git-ignored and
must stay that way.
