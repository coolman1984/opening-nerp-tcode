"""Run one `gmes` command as a child process, and act only if it goes
completely silent - never merely because it failed.

Every failure handled elsewhere in this package - the recovery ladder
(Phase 46), the circuit breaker (Phase 50), the batch checkpoint (Phase
51) - is either a caught exception or a process that eventually exits.
This is for the remaining case: a hang with no exception at all. Nothing
inside a stuck process can see that about itself, so this watches from
outside, the same pattern systemd's own service watchdog and process
supervisors use - poll a liveness signal, enforce a timeout, act only when
it goes stale.

`heartbeat.py` is what the child writes; this is what reads it from a
second process, which is the only way a hang can be told apart from
merely slow, legitimate work.
"""
import subprocess
import sys
import time

from . import alerts, heartbeat
from ..paths import heartbeat_path, log_path

DEFAULT_STALE_AFTER = 1800   # generous: a real screen can legitimately take minutes
DEFAULT_POLL = 15
DEFAULT_RESTARTS = 1


def _command(argv):
    """How to re-invoke this same program with a plain argument list.

    A frozen build's `sys.executable` IS the packaged `GMES.exe` already;
    a source checkout needs `-m gmes` in front of it. Getting this wrong
    would spawn a bare Python interpreter with no program to run."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *argv]
    return [sys.executable, "-m", "gmes", *argv]


def _kill(process, log):
    """Stop this child and everything it spawned - including Chrome.

    The process that owned Chrome just proved it cannot be trusted to
    close it itself, so nothing here asks it to. The next attempt starts
    on a closed browser, exactly like any other cold start
    (session_uc.cold_start) - never `taskkill /IM chrome.exe`, which would
    take every Chrome window on the machine (CLAUDE.md 2.6); `/PID` with
    `/T` reaches only this process's own children."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, timeout=15)
        else:
            process.terminate()
        process.wait(timeout=15)
    except Exception as error:
        log(f"supervise: could not confirm the stuck process stopped ({error})")
        try:
            process.kill()
        except Exception:
            pass


def run_supervised(argv, stale_after=DEFAULT_STALE_AFTER, poll=DEFAULT_POLL,
                   restarts=DEFAULT_RESTARTS, log=print, spawn=subprocess.Popen):
    """Run `gmes <argv>` as a child, restarting it once if it stops
    answering entirely.

    A process that exits on its own is reported exactly as it exited -
    this never turns a real failure into a false success, and never turns
    a real success into anything else. Only silence for the whole
    `stale_after` window is treated as a hang - and silence includes never
    having beaten at all. `age_seconds()` returns None both when there is
    no heartbeat yet (Chrome is still starting) and when there will never
    be one (the process died before writing its first beat); the two look
    identical from here, so both are timed from when THIS attempt was
    spawned, not treated as an unbounded grace period. A process stuck
    before its first beat used to loop here forever, never declared stuck
    at any `stale_after` value - see HISTORY.md Phase 54.1."""
    heartbeat.clear()   # a stale beat from an unrelated earlier run must
                        # never look like progress from this attempt
    command = _command(argv)
    attempt = 0
    while True:
        attempt += 1
        log(f"supervise: starting attempt {attempt}: {' '.join(command)}")
        process = spawn(command)
        spawned_at = time.monotonic()
        while True:
            code = process.poll()
            if code is not None:
                log(f"supervise: the process exited on its own (code {code})")
                return code
            age = heartbeat.age_seconds()
            if age is None:
                age = time.monotonic() - spawned_at
            if age > stale_after:
                log(f"supervise: no progress for {age:.0f}s (limit {stale_after:.0f}s) - "
                    "treating it as stuck and stopping it")
                _kill(process, log)
                break
            time.sleep(poll)
        if attempt > restarts:
            log(f"supervise: gave up after {attempt} attempt(s) that never responded")
            alerts.notify(
                f"G-MES supervised run did not respond: {' '.join(command)}",
                f"Stopped after {attempt} attempt(s) that never answered "
                f"(no progress for over {stale_after:.0f}s each time).\n\n"
                f"This was killed and given up on by the external watchdog, so the "
                f"run's own failure alert (if any) never had a chance to send - "
                f"this is that alert instead.\n\nFull log: {log_path()}",
                log=log)
            return 1
        heartbeat.clear()
