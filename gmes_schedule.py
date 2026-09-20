"""
Scheduling batches with Windows Task Scheduler.

    create('morning', parse_when('06:30', daily=True))
    list_tasks()            -> what is scheduled, when it next runs, how the last run ended
    run_now('morning')      -> start the scheduled task immediately
    delete('morning')

**What a scheduled run needs, and why it is set up this way.** The tool signs in
with a credential stored under YOUR Windows account (DPAPI) and drives a real
browser window. Both need a signed-in Windows session, so the task is
registered for the current user and runs ONLY WHILE THEY ARE SIGNED IN - it will
not fire on a locked-out or logged-off PC. That is a property of how the
credentials are protected (CLAUDE.md 2.2), not an omission here. A PC that is
asleep at the scheduled time runs the task when it wakes (`StartWhenAvailable`);
a run still going when the next one is due is not started twice.

The task itself is one line - a small launcher `.cmd` under `schedules/` - so
the command stays short and readable, and what actually runs is the SAVED BATCH
of that name: edit the batch and the schedule follows.

Talks to PowerShell's ScheduledTasks cmdlets rather than `schtasks.exe`, because
`schtasks /SD` takes the date in the machine's regional format and a wrong guess
silently schedules the wrong day.
"""
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

import gmes_batch
import gmes_core as core

PREFIX = "GMES_Batch_"
SCHEDULE_DIR = os.path.join(core.SCRIPT_DIR, "schedules")

_DAYS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
         "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]


class ScheduleError(RuntimeError):
    """Task Scheduler refused, or could not be reached. The message is the
    system's own, so a person can act on it."""


@dataclass
class When:
    at: str                                   # "HH:MM", 24 hour
    kind: str = "daily"                       # daily | weekly | once
    days: list = field(default_factory=list)  # ["mon", ...] for weekly
    on: str = ""                              # "YYYY-MM-DD" for once


def parse_when(at, daily=False, weekdays=False, days=None, once=None):
    """What a person typed -> a validated When. Exactly one recurrence must be
    named - a schedule that could be read two ways is refused, not guessed at."""
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", (at or "").strip()):
        raise ValueError(f"{at!r} is not a time - use 24 hour HH:MM, e.g. 06:30")
    hh, mm = at.strip().split(":")
    at = f"{int(hh):02d}:{mm}"
    named = [bool(daily), bool(weekdays), bool(days), bool(once)]
    if sum(named) != 1:
        raise ValueError("say how often, exactly one of: --daily, --weekdays, "
                         "--days mon,wed,fri, or --once YYYY-MM-DD")
    if daily:
        return When(at, "daily")
    if weekdays:
        return When(at, "weekly", list(_WEEKDAYS))
    if days:
        parts = [d.strip().lower()[:3] for d in re.split(r"[,\s]+", days) if d.strip()]
        bad = [d for d in parts if d not in _DAYS]
        if bad or not parts:
            raise ValueError(f"unknown day(s) {bad or days!r} - use mon,tue,wed,thu,fri,sat,sun")
        ordered = [d for d in _DAYS if d in parts]
        return When(at, "weekly", ordered)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", once.strip()):
        raise ValueError(f"{once!r} is not a date - use YYYY-MM-DD")
    from datetime import datetime
    try:
        datetime.strptime(once.strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{once!r} is not a real date") from None
    return When(at, "once", on=once.strip())


def describe_when(when):
    if when.kind == "daily":
        return f"every day at {when.at}"
    if when.kind == "once":
        return f"once, on {when.on} at {when.at}"
    if when.days == _WEEKDAYS:
        return f"every weekday at {when.at}"
    return f"every {', '.join(d.capitalize() for d in when.days)} at {when.at}"


def task_name(batch):
    if not gmes_batch.valid_name(batch):
        raise ValueError("a batch name is letters, digits, - or _ (at most 40)")
    return PREFIX + batch


# ---------------------------------------------------------------------------
# The launcher the task runs
# ---------------------------------------------------------------------------

def launcher_path(batch):
    task_name(batch)                                     # validates
    return os.path.join(SCHEDULE_DIR, f"run_{batch}.cmd")


def launcher_text(batch, python=None, repo=None):
    """What the task actually executes: change into the project folder, run the
    saved batch unattended, append everything to a per-batch log."""
    python = python or sys.executable
    repo = repo or core.SCRIPT_DIR
    return "\r\n".join([
        "@echo off",
        f'cd /d "{repo}"',
        "if not exist logs mkdir logs",
        # -u: with stdout redirected to a file Python buffers in blocks, so a
        # run that hangs or is killed would leave an EMPTY log - the one thing
        # an unattended job must not do (HISTORY.md Phase 83).
        f'"{python}" -u gmes_batch.py run --batch {batch} --unattended '
        f'>> "logs\\scheduled_{batch}.log" 2>&1',
        "exit /b %errorlevel%",
        ""])


def write_launcher(batch, python=None, repo=None):
    os.makedirs(SCHEDULE_DIR, exist_ok=True)
    path = launcher_path(batch)
    with open(path, "w", encoding="ascii", errors="replace", newline="") as fh:
        fh.write(launcher_text(batch, python, repo))
    return path


# ---------------------------------------------------------------------------
# PowerShell
# ---------------------------------------------------------------------------

def _q(value):
    """A PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(script, timeout=90):
    """(returncode, stdout, stderr). The one place the system is touched, so
    tests replace exactly this."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ScheduleError("Windows PowerShell was not found, so Task Scheduler "
                            "cannot be reached from here") from None
    except subprocess.TimeoutExpired:
        raise ScheduleError("Task Scheduler did not answer within "
                            f"{timeout} seconds") from None
    return r.returncode, r.stdout, r.stderr


def _trigger_script(when):
    if when.kind == "daily":
        return f"New-ScheduledTaskTrigger -Daily -At {_q(when.at)}"
    if when.kind == "weekly":
        days = ",".join(_DAYS[d] for d in when.days)
        return f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {days} -At {_q(when.at)}"
    return f"New-ScheduledTaskTrigger -Once -At ([datetime]{_q(when.on + ' ' + when.at)})"


def create_script(batch, when, launcher, repo):
    name = task_name(batch)
    description = f"G-MES batch '{batch}' - {describe_when(when)}. Managed by gmes_batch.py."
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$action = New-ScheduledTaskAction -Execute {_q(launcher)} -WorkingDirectory {_q(repo)}",
        f"$trigger = {_trigger_script(when)}",
        # StartWhenAvailable: a PC asleep at the time still runs it on waking.
        # IgnoreNew: a run still going is never started a second time.
        "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable "
        "-MultipleInstances IgnoreNew -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 6)",
        f"Register-ScheduledTask -TaskName {_q(name)} -Action $action -Trigger $trigger "
        f"-Settings $settings -Description {_q(description)} -Force | Out-Null",
    ])


def create(batch, when, python=None, repo=None):
    """Write the launcher and register the task. Returns the task name."""
    repo = repo or core.SCRIPT_DIR
    launcher = write_launcher(batch, python, repo)
    rc, out, err = _run_powershell(create_script(batch, when, launcher, repo))
    if rc != 0:
        raise ScheduleError((err or out or "Task Scheduler refused the task").strip())
    return task_name(batch)


def list_script():
    return "\n".join([
        "$ErrorActionPreference = 'SilentlyContinue'",
        f"$rows = @(Get-ScheduledTask -TaskName '{PREFIX}*' | ForEach-Object {{",
        "  $i = $_ | Get-ScheduledTaskInfo",
        "  $fmt = { param($d) if ($d -and $d.Year -gt 2000) { $d.ToString('s') } else { '' } }",
        "  [pscustomobject]@{",
        "    name = $_.TaskName; state = [string]$_.State",
        "    next = (& $fmt $i.NextRunTime); last = (& $fmt $i.LastRunTime)",
        "    result = $i.LastTaskResult",
        "    trigger = (($_.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task','' -replace 'Trigger','' }) -join ',')",
        "  }",
        "})",
        "if ($rows.Count -eq 0) { '[]' } else { ConvertTo-Json -InputObject $rows -Compress }",
    ])


def parse_list(stdout):
    """PowerShell's JSON -> a tidy list. One task comes back as an object, none
    as an empty array - both are normalised."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        raise ScheduleError(f"Task Scheduler's answer could not be read: {text[:120]!r}") from None
    if isinstance(data, dict):
        data = [data]
    out = []
    for row in data:
        name = str(row.get("name", ""))
        if not name.startswith(PREFIX):
            continue
        result = row.get("result")
        out.append({"batch": name[len(PREFIX):], "task": name,
                    "state": row.get("state", ""), "next_run": row.get("next", ""),
                    "last_run": row.get("last", ""), "last_result": result,
                    "trigger": row.get("trigger", ""),
                    "last_ok": result in (0, None) if row.get("last") else None})
    return out


def list_tasks():
    rc, out, err = _run_powershell(list_script())
    if rc != 0:
        raise ScheduleError((err or "Task Scheduler could not be read").strip())
    return parse_list(out)


def delete(batch):
    """Remove the task and its launcher. Returns True if a task was removed."""
    name = task_name(batch)
    script = ("$ErrorActionPreference = 'Stop'\n"
              f"if (Get-ScheduledTask -TaskName {_q(name)} -ErrorAction SilentlyContinue) "
              f"{{ Unregister-ScheduledTask -TaskName {_q(name)} -Confirm:$false; 'removed' }} "
              "else { 'absent' }")
    rc, out, err = _run_powershell(script)
    if rc != 0:
        raise ScheduleError((err or out or "Task Scheduler refused").strip())
    try:
        os.unlink(launcher_path(batch))
    except OSError:
        pass
    return "removed" in out


def run_now(batch):
    name = task_name(batch)
    script = ("$ErrorActionPreference = 'Stop'\n"
              f"Start-ScheduledTask -TaskName {_q(name)}")
    rc, out, err = _run_powershell(script)
    if rc != 0:
        raise ScheduleError((err or out or f"there is no scheduled task for {batch!r}").strip())
    return name
