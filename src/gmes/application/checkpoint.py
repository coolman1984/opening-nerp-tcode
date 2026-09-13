"""Resume a batch a full process crash interrupted, without redoing screens
that already delivered a real file.

The recovery ladder (Phase 46) and the circuit breaker (Phase 50) both
assume the Python process is alive to make a decision. Neither helps when
the process itself dies mid-batch - power loss, an OS update forcing a
reboot, someone killing the wrong task in Task Scheduler. The next launch
starts the batch over from the first screen, including the ones that
already exported a checked file five minutes before the crash.

This is a checkpoint in the classic batch-processing sense: a snapshot of
progress on persistent storage, read back on the next attempt so it can
pick up after the last one it proved rather than at the beginning. Two
things keep it from being a hazard:

* The record is keyed by a digest of what the batch ASKS FOR, never what
  it proves. Change any argument - a different date range is the ordinary
  case, since most nightly invocations compute "yesterday" fresh each
  night - and it is a different batch with no record to resume, by
  construction rather than by remembering to invalidate anything.
* Only a screen that actually SUCCEEDED is ever skipped on resume. A
  screen that failed, or was never reached, is attempted exactly as if
  nothing had been recorded - resuming only ever removes redundant work,
  never a chance to fix something.

A record older than `MAX_AGE` is treated as if it did not exist, so a
fixed command run again by mistake a week later does not silently skip
work on the strength of a crash nobody remembers.
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta

from ..contracts import RunResult
from ..paths import batches_dir

MAX_AGE = timedelta(hours=6)


def _signature(specs):
    """A stable id for 'the same batch', from what each spec asks for."""
    parts = [
        "|".join(str(part) for part in (
            spec.screen_code, spec.division, spec.tree, spec.date_from, spec.date_to,
            sorted(spec.sets.items()), spec.options, spec.export, spec.grid_name,
            spec.verify, spec.out_dir))
        for spec in specs
    ]
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


def _path_for(specs):
    return batches_dir() / f"{_signature(specs)}.json"


def _read(specs):
    try:
        with _path_for(specs).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        age = datetime.now() - datetime.strptime(data.get("started", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if age > MAX_AGE:
        return None
    return data


def completed(specs):
    """Screen codes already proved to have succeeded in this exact batch,
    mapped to enough of their result to report without re-running them."""
    data = _read(specs)
    return dict((data or {}).get("completed", {}))


def record(specs, result: RunResult):
    """Note one more screen delivered - called only for a real success."""
    if not result.ok:
        return
    path = _path_for(specs)
    data = _read(specs) or {"started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "completed": {}}
    data["completed"][result.screen] = {
        "rows": result.rows, "files": list(result.files),
        "duration_s": result.duration_s,
    }
    fd, temporary = tempfile.mkstemp(prefix=".batch-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def clear(specs):
    """Drop the record once nothing about this batch is left to resume."""
    try:
        _path_for(specs).unlink()
    except OSError:
        pass


def resumed_result(screen_code, record_entry) -> RunResult:
    """Rebuild just enough of a RunResult to report a resumed screen
    honestly: it delivered a file, proved by an earlier process, not by
    this one - nothing else about it is re-asserted."""
    return RunResult(screen=screen_code, ok=True, rows=int(record_entry.get("rows", 0)),
                     files=tuple(record_entry.get("files", [])),
                     duration_s=float(record_entry.get("duration_s", 0.0)))
