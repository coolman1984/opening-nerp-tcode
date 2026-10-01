"""GMES Automation - start here.

    (no arguments)   the window: a local page in a Chrome/Edge app window (web_server.py)
    --batch NAME [--unattended]   run a saved batch without a window (what a schedule runs)
    --selftest       login, browsers, recordings - no sign-in

The window's pages:
    Reports      every recorded screen: status, last run, record check; run, re-record
    Record       any UI number: find, describe, choose scope, record + full record check
    Run & Batch  several screens in one browser session; save as a named batch
    Schedules    run a saved batch every day / on weekdays (Windows Task Scheduler)
    Row export   one Excel per row of a list (double-click a cell -> popup -> Excel)
    History      every run report; support package; self-test
    Account      the person's own G-MES login and which browser profile is used
    Appearance   theme, fonts, text size
"""
import os
import sys

import app_env

if app_env.FROZEN and sys.stdout is None:            # a windowed .exe has no console
    os.makedirs(os.path.join(app_env.data_dir(), "logs"), exist_ok=True)
    _console = open(os.path.join(app_env.data_dir(), "logs", "console.txt"), "a", buffering=1,
                    encoding="utf-8")
    sys.stdout = sys.stderr = _console

app_env.setup()

import service                                # noqa: E402

VERSION = "2.0"


def selftest():
    import account
    import sync_engine
    print(f"{app_env.APP_NAME} {VERSION} self-test")
    print("  data folder  :", app_env.data_dir())
    user, problem = account.saved_login()
    print("  login        :", f"saved ({user})" if user else (problem or "not saved yet (Account page)"))
    info = account.describe_browsers()
    found = [b["label"] for b in info["browsers"] if b["installed"]]
    print("  browsers     :", ", ".join(found) or "none found", "| default:", info["default"])
    print("  browser copy :", account.setup_sentence(info))
    print("  recordings   :", sum(1 for c in service.library() if c["recorded"]), "recorded here,",
          len(service.library()), "known")
    if not app_env.FROZEN:
        problems = sync_engine.check()
        print("  engine copy  :", "identical to the project" if not problems else problems)
    try:
        import websocket                                     # noqa: F401
        print("  websocket    : ok")
    except ImportError:
        print("  websocket    : MISSING")
        return 1
    try:
        import web_server
        web_server.web_dir()
        print("  window files : ok")
    except Exception as e:                                   # noqa: BLE001
        print("  window files : MISSING", e)
        return 1
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if "--batch" in argv:
        i = argv.index("--batch")
        if i + 1 >= len(argv):
            print("--batch needs the name of a saved batch")
            return 2
        return service.headless_batch(argv[i + 1], unattended="--unattended" in argv)
    import web_server
    return web_server.serve(selftest=selftest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
