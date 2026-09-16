"""
Read-only preflight check: is this machine ready to run the G-MES automation
at all, before the first real sign-in spends any of the account's patience
on a problem this could have caught in under a second.

    python gmes_preflight.py

`GMES_Workflow.bat` runs this before doing anything else - the same
"`where python` failed, stop here" discipline the launcher already had,
generalised to the checks a fresh machine actually needs:

  1. Python version           - a floor this project's own syntax needs.
  2. websocket-client         - the one third-party dependency; everything
                                 else is stdlib (CLAUDE.md 4.5).
  3. A supported browser      - Chrome or Edge (gmes_browsers.py).
  4. The runtime directory is writable - credentials.dat, the browser
                                 profile, and the first-run record all live
                                 under %LOCALAPPDATA%\\GMES_Automation.

Exit code 0 if every check passes, 1 otherwise, and every check still runs
and reports even after an earlier one fails - so fixing one problem does not
mean running this five times to discover the next.

**What this deliberately does NOT check: whether Chrome or Edge will actually
answer on a CDP port, or whether AD SSO will complete.** Either can only be
proven by actually launching the browser and signing in - which is the
expensive step this tool exists to fail BEFORE, not repeat. This is a
preflight, not a dry run.
"""
import importlib.util
import os
import sys

MIN_PYTHON = (3, 10)


def check_python_version():
    # Indexed, not `.major`/`.minor`/`.micro`: the real sys.version_info
    # supports both, but comparing it against the plain tuple MIN_PYTHON
    # already relies on tuple semantics, so working entirely in tuple terms
    # keeps this testable with an ordinary tuple standing in for it.
    have = tuple(sys.version_info[:3])
    ok = have >= MIN_PYTHON
    have_str = ".".join(str(v) for v in have)
    need_str = ".".join(str(v) for v in MIN_PYTHON)
    if ok:
        return True, f"Python {have_str} (>= {need_str})"
    return False, (f"Python {have_str} is older than {need_str}. Install a "
                   "newer Python 3 and run the scripts with it.")


def check_websocket_client():
    if importlib.util.find_spec("websocket") is None:
        return False, ("websocket-client is not installed. Install it with:  "
                       f"{sys.executable} -m pip install -r requirements.txt")
    try:
        import websocket
        version = getattr(websocket, "__version__", None) or "installed"
    except Exception as e:
        return False, f"found but could not import websocket-client ({e})"
    return True, f"websocket-client {version}"


def check_browser():
    try:
        import gmes_browsers
    except Exception as e:
        return False, f"could not import gmes_browsers.py ({e})"
    found = []
    for key in gmes_browsers.SUPPORTED:
        path = gmes_browsers.find_executable(key)
        if path:
            found.append(f"{gmes_browsers.spec(key)['short']} ({path})")
    if found:
        return True, ", ".join(found)
    return False, ("Neither Chrome nor Edge was found. Install one of them, "
                   "or set CHROME_PATH / EDGE_PATH to its full path.")


def check_runtime_directory():
    try:
        import gmes_browsers
    except Exception as e:
        return False, f"could not import gmes_browsers.py ({e})"
    root = gmes_browsers.AUTOMATION_ROOT
    probe = os.path.join(root, ".preflight-write-test")
    try:
        os.makedirs(root, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.unlink(probe)
    except OSError as e:
        return False, (f"cannot write to {root!r} ({e}). Credentials, the "
                       "browser profile and the first-run record all live "
                       "there - check permissions on %LOCALAPPDATA%.")
    return True, root


# Order matters only in that each is independent - nothing here depends on an
# earlier check having passed, deliberately, so one failure never hides
# another (HISTORY.md Phase 79 - the review that asked for this named
# exactly that gap: GMES_Workflow.bat's only check was `where python`).
CHECKS = (
    ("Python version", check_python_version),
    ("websocket-client", check_websocket_client),
    ("Browser (Chrome or Edge)", check_browser),
    ("Runtime directory writable", check_runtime_directory),
)


def run(verbose=True):
    """Run every check, in order, and keep going past a failure.

    Returns True only if every single one passed. A check that raises
    something its own try/except did not anticipate is caught here too -
    a bug in this tool must never look like "everything is fine" by
    accident, and must never itself crash the launcher it is meant to
    protect."""
    all_ok = True
    for name, check in CHECKS:
        try:
            ok, detail = check()
        except Exception as e:
            ok, detail = False, f"check itself raised: {e!r}"
        all_ok = all_ok and ok
        if verbose:
            mark = "OK  " if ok else "FAIL"
            print(f"  [{mark}] {name:<28} {detail}")
    return all_ok


def main():
    print("G-MES preflight check")
    print("=" * 70)
    ok = run()
    print("=" * 70)
    if ok:
        print("Ready.")
        return 0
    print("Not ready - fix the FAIL line(s) above before running a report.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
