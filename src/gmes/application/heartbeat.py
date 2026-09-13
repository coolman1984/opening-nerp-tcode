"""A liveness signal for the one failure mode the ladder and the breaker
cannot see: a genuine hang.

Every failure handled so far - the recovery ladder (Phase 46), the circuit
breaker (Phase 50), the batch checkpoint (Phase 51) - is a caught
exception or a process that exits. None of them help against a native
call, an OS-level deadlock, or a bug nobody anticipated that never raises
and never returns. Nothing INSIDE the stuck process can detect that about
itself, by definition - the only place left to look from is outside it,
which is what `application/supervisor_uc.py` does with what this module
writes.
"""
import json
import os
import tempfile
from datetime import datetime

from ..paths import heartbeat_path

_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def beat(detail=""):
    """Record that the CALLING process is still making progress.

    Always its own pid, never anyone else's - `heartbeat_path()` defaults
    to `os.getpid()`, which is exactly the id the parent that spawned this
    process (`supervisor_uc.run_supervised`) already has as `process.pid`,
    with no coordination needed between the two.

    Cheap and safe to call often, and never worth stopping real work over:
    any error writing it is swallowed rather than raised, because a
    process that crashes while recording that it is alive would be a
    worse outcome than the one this exists to catch."""
    try:
        path = heartbeat_path()
        payload = {"at": datetime.now().strftime(_FORMAT),
                   "pid": os.getpid(), "detail": str(detail)[:200]}
        fd, temporary = tempfile.mkstemp(prefix=".heartbeat-", dir=path.parent, text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temporary, path)
    except OSError:
        pass


def read(pid=None):
    """The last recorded beat for `pid` (default: the caller's own), or
    None if there has never been one (or it cannot be read - a partially
    written file mid-replace looks the same as no file to a supervisor,
    and is treated the same safe way)."""
    try:
        with heartbeat_path(pid).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def age_seconds(pid=None):
    """Seconds since the last beat for `pid`, or None if there never was one."""
    data = read(pid)
    if not data:
        return None
    try:
        at = datetime.strptime(data["at"], _FORMAT)
    except (KeyError, ValueError):
        return None
    return (datetime.now() - at).total_seconds()


def clear(pid=None):
    """Remove the record for `pid`. The supervisor calls this with the
    exact child pid it just spawned, right after spawning it - never a
    shared, pid-less file - so a leftover heartbeat from a long-dead
    process that happened to reuse this pid can never be mistaken for an
    ancient hang the instant the new one starts, and cleans the file up
    once that pid is done with it."""
    try:
        heartbeat_path(pid).unlink()
    except OSError:
        pass
