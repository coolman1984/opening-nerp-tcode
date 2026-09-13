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
    """Record that the process is still making progress.

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


def read():
    """The last recorded beat, or None if there has never been one (or it
    cannot be read - a partially written file mid-replace looks the same
    as no file to a supervisor, and is treated the same safe way)."""
    try:
        with heartbeat_path().open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def age_seconds():
    """Seconds since the last beat, or None if there has never been one."""
    data = read()
    if not data:
        return None
    try:
        at = datetime.strptime(data["at"], _FORMAT)
    except (KeyError, ValueError):
        return None
    return (datetime.now() - at).total_seconds()


def clear():
    """Remove the record. Called before a fresh attempt starts, so a stale
    beat from an unrelated earlier run can never look like progress from
    this one."""
    try:
        heartbeat_path().unlink()
    except OSError:
        pass
