"""The sign-in budget: how often this PC may start a corporate (AD SSO) sign-in, so recovering from a
failed one never becomes the thing that blocks the account (HISTORY.md Phase 132).

Two real limits sit behind it:
  * Samsung's SSO stopped opening its window after many sign-ins in one hour (2026-10-10: two
    failures in a row; it worked again after a pause) - more attempts only lengthen the pause.
  * AD FS locks an account after a few bad passwords in a window (Microsoft's example: 4 in 60
    minutes). The tool never re-sends a password after an unclear result (gmes_login), and this
    budget refuses even a first submission when two already went unanswered within the hour.

The ledger is one line per event in %LOCALAPPDATA%\\GMES_Automation\\signin_ledger.jsonl - shared by
the command line and GMES Automation on this PC, times and outcomes only, never a name or a
password:  sso_click | no_window | submitted | signed_in | rejected | unclear
"""
import datetime as _dt
import json
import os

WINDOW_MINUTES = 60
MAX_CLICKS = 8            # AD SSO starts per hour, every recovery step included
MAX_NO_WINDOW = 4         # SSO windows that never opened within the hour -> cool down (one run's whole ladder)
COOL_DOWN_MINUTES = 30    # after that: the owner's own rule ("wait at least 30 minutes")
MAX_UNANSWERED = 2        # submissions without a sign-in within the hour -> stop (lockout)


def ledger_path():
    override = os.environ.get("GMES_SIGNIN_LEDGER")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "GMES_Automation", "signin_ledger.jsonl")


def record(kind, now=None, **detail):
    """Add one event. Never raises - the budget must not be the thing that fails a sign-in."""
    try:
        path = ledger_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entry = {"at": (now or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), "kind": kind}
        entry.update({k: v for k, v in detail.items() if v is not None and k not in ("user", "password")})
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry
    except Exception:                                        # noqa: BLE001
        return None


def events(minutes=WINDOW_MINUTES, now=None):
    """[(datetime, kind)] of the last `minutes`, oldest first."""
    now = now or _dt.datetime.now()
    since = now - _dt.timedelta(minutes=minutes)
    out = []
    try:
        with open(ledger_path(), encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                    at = _dt.datetime.strptime(e["at"], "%Y-%m-%d %H:%M:%S")
                except (ValueError, KeyError, TypeError):
                    continue
                if since <= at <= now:
                    out.append((at, e.get("kind")))
    except OSError:
        pass
    return out


def may_try(now=None):
    """(allowed, minutes to wait, why). Asked before EVERY AD SSO click."""
    now = now or _dt.datetime.now()
    recent = events(now=now)
    since_success = [k for at, k in recent]
    if "signed_in" in since_success:                         # only what came after the last success counts
        last = max(i for i, k in enumerate(since_success) if k == "signed_in")
        recent = recent[last + 1:]
    if any(k == "rejected" for _at, k in recent):
        return False, None, ("G-MES refused the credentials within the last hour - nothing is tried again "
                             "until a person has signed in by hand")
    unanswered = sum(1 for _at, k in recent if k == "submitted")       # since the last sign-in
    if unanswered >= MAX_UNANSWERED:
        return False, WINDOW_MINUTES, (f"{MAX_UNANSWERED} password submissions went unanswered within the hour - "
                                       "stopping well before the account locks; sign in by hand once")
    no_window = [at for at, k in recent if k == "no_window"]
    if len(no_window) >= MAX_NO_WINDOW:
        wait = COOL_DOWN_MINUTES - (now - no_window[-1]).total_seconds() / 60
        if wait > 0:
            return False, round(wait), (f"the Samsung SSO window failed to open {len(no_window)} times within the hour - "
                                        f"it is throttling; waiting {round(wait)} more minute(s) helps, trying does not")
    clicks = [at for at, k in events(now=now) if k == "sso_click"]
    if len(clicks) >= MAX_CLICKS:
        wait = WINDOW_MINUTES - (now - clicks[0]).total_seconds() / 60
        return False, max(1, round(wait)), (f"{len(clicks)} corporate sign-ins were started within the hour - "
                                            f"the budget is {MAX_CLICKS}; the next one is allowed in {max(1, round(wait))} minute(s)")
    return True, 0, ""


def summary(now=None):
    """One line about the last hour, for a self-test."""
    recent = events(now=now)
    counts = {}
    for _at, k in recent:
        counts[k] = counts.get(k, 0) + 1
    ok, wait, why = may_try(now=now)
    return (", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no sign-in attempts") + \
        " in the last hour - " + ("a sign-in may start" if ok else f"WAIT: {why}")
