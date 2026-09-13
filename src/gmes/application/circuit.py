"""Stop spending a recovery budget on a screen that has been broken for days.

The recovery ladder (`recovery.py`) makes one night's run resilient: it
reattaches, reloads, and restarts the browser until a screen either succeeds
or exhausts a wall-clock budget. It has no memory between separate runs -
by design, since a fresh run should not inherit a stale assumption about the
browser or the session.

But that means a screen that has genuinely broken - the menu path changed,
the account lost access, the report was retired - burns the FULL recovery
budget again on the next run, and the one after that, forever, for an
answer that has not changed in days. This is the pattern message queues
call a poison message and RPA platforms call a broken selector that needs a
human: something that will not succeed no matter how many times it is
retried needs to stop being retried and start being looked at.

This is deliberately not folded into the ladder. The ladder decides what to
do WITHIN one run; this decides whether a run is worth attempting AT ALL,
using history the ladder never sees. A screen is skipped, never blocked
forever: any success closes it outright, and `--force` always attempts
regardless of what happened before - the escape hatch every refusal in this
project is required to have (see HISTORY.md Phase 48.2's --relearn).
"""
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime

from ..paths import circuit_dir

DEFAULT_THRESHOLD = 3

_SCREEN_CODE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class BreakerState:
    """What is known about one screen's recent run history."""
    consecutive_failures: int = 0
    last_reason: str = ""
    last_at: str = ""

    def is_open(self, threshold=DEFAULT_THRESHOLD):
        return self.consecutive_failures >= threshold


def _path_for(code):
    safe = "".join(_SCREEN_CODE.findall(str(code).strip().upper()))
    if not safe:
        raise ValueError("screen code must contain at least one letter or digit")
    return circuit_dir() / f"{safe}.json"


def load(code) -> BreakerState:
    """Read one screen's history. Missing or unreadable is a clean slate,
    same as a screen that has never failed - the breaker is a convenience,
    not a ledger that has to survive corruption."""
    try:
        with _path_for(code).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return BreakerState(consecutive_failures=int(data.get("consecutive_failures", 0)),
                            last_reason=str(data.get("last_reason", "")),
                            last_at=str(data.get("last_at", "")))
    except (OSError, ValueError, TypeError, KeyError):
        return BreakerState()


def _save(code, state: BreakerState):
    path = _path_for(code)
    payload = {"consecutive_failures": state.consecutive_failures,
               "last_reason": state.last_reason, "last_at": state.last_at}
    fd, temporary = tempfile.mkstemp(prefix=".circuit-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def record_success(code):
    """Any real success closes the breaker outright.

    No gradual healing, no half-open trial count: an export that actually
    landed is stronger proof than any number of clean health checks could
    be, so there is nothing gradual left to do."""
    if load(code).consecutive_failures:
        _save(code, BreakerState())


def record_failure(code, reason):
    """One more run ended without a delivered result, for whatever reason -
    a fault the ladder exhausted its budget on, or a refusal it never
    retried. Both count: a filter value that has been wrong every night for
    a week is exactly as worth flagging as a browser that will not start."""
    state = load(code)
    _save(code, BreakerState(consecutive_failures=state.consecutive_failures + 1,
                             last_reason=str(reason)[:300],
                             last_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def check(code, threshold=DEFAULT_THRESHOLD):
    """None when this screen is worth attempting; otherwise the sentence to
    report instead of attempting it."""
    state = load(code)
    if not state.is_open(threshold):
        return None
    return (f"{code} has failed {state.consecutive_failures} runs in a row "
            f"(last: {state.last_reason!r}, at {state.last_at}). Skipped rather than "
            f"spend the recovery budget again on a screen that has not delivered "
            f"anything in days. Run 'gmes run {code} --force' once it is fixed, "
            f"or to try again anyway.")
