"""Is this PC ready to run the batches by itself, tonight and every night?

    python gmes_server.py              the readiness check (also: GMES_Workflow.bat server)
    python gmes_server.py setup        the check, then - asking first - save the sign-in and
                                       create the schedules the package came with
    python gmes_server.py verify       the package arrived complete and undamaged
    python gmes_server.py move-folder OLD NEW
                                       recordings and batches that save to OLD save to NEW
    python gmes_server.py help         every command of the tool on one screen

A scheduled night that fails usually fails for a reason that was true at 17:00 already:
a folder that exists on the old PC only, a network folder this account may not write
to, a schedule still pointing at the folder the tool was copied FROM, a server that
restarted for Windows Update and is now sitting at the sign-in screen, a machine that
goes to sleep. Every one of them is checked here, said in plain words, with what to do.

The check reads; the only things it writes are a tiny test file in each output folder,
deleted at once (a folder this Windows account cannot write to is the commonest server
failure, and only a write proves it - `--no-write-test` skips it). It never signs in to
G-MES and never opens the saved sign-in (CLAUDE.md 2.1a: existence only).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
MARK = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL", INFO: "  - "}
PERSONAL = re.compile(r"^[A-Za-z]:\\Users\\([^\\]+)(\\|$)", re.I)
FIXED_POLICIES = ("yesterday", "today", "lastweek", "thisweek")   # the MOVING ones: worked out each run
FOLDER_TIMEOUT = 15

HELP = r"""GMES TOOL - every command on one screen
=======================================

EVERY DAY
  GMES_Workflow.bat                          the menu: run, set up, batches, schedules, history
  GMES_Workflow.bat P1112UM00                run one recorded report as it was recorded
  GMES_Workflow.bat status                   every report, its status and last record check

RECORD A NEW SCREEN (once per screen)
  GMES_Workflow.bat find "production plan"   find a screen's code
  GMES_Workflow.bat describe P1112UM00       what the screen offers
  GMES_Workflow.bat record P1112UM00 --division VD --date 20261006 --verify planYmd
                                             record it AND prove it (bare replay, judged)
  GMES_Workflow.bat check P1112UM00          prove an earlier recording again

BATCHES AND SCHEDULES
  python gmes_batch.py save morning P1112UM00 P3111UM00 --date yesterday
  python gmes_batch.py schedule morning --at 06:30 --weekdays
  python gmes_batch.py schedules             what runs when, and how it last ended
  python gmes_batch.py run --batch morning   run it now

ONE EXCEL PER ROW OF A LIST
  GMES_Workflow.bat rowexport --period previous

THE SERVER
  GMES_Workflow.bat server                   is this PC ready for tonight? (changes nothing)
  GMES_Workflow.bat setup                    make it ready (asks before every change)
  GMES_Workflow.bat verify                   did the package arrive complete?
  GMES_Workflow.bat move-folder OLD NEW      reports that saved to OLD now save to NEW
  GMES_Workflow.bat package                  make a folder + zip to move the tool again

THE WINDOW (GMES Automation) beside this tool, on the PC that has it
  GMES_Workflow.bat sync                     same recordings, batches, checks and history
  GMES_Workflow.bat parity                   every window feature and its command here

Exit codes: 0 ok, 1 something failed, 2 a command was typed wrong, 3 another run held the
browser, 4 sign-in failed.
"""


class Result:
    def __init__(self, status, title, detail="", fix=""):
        self.status, self.title, self.detail, self.fix = status, title, detail, fix

    def __repr__(self):                                    # for test failure messages
        return f"Result({self.status!r}, {self.title!r}, {self.detail!r})"


# --------------------------------------------------------------------------
# Folders the reports are saved to
# --------------------------------------------------------------------------
def _read(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _norm(path):
    return os.path.normcase(os.path.normpath(str(path).strip().rstrip("\\/"))) if path else ""


def pinned_folders(root=None):
    """[({path, personal, user}, [who saves there])] for every folder a recording or a
    saved batch is pinned to, plus the default output folder (always used)."""
    root = root or HERE
    import gmes_core
    seen, order = {}, []

    def add(path, who):
        if not path or not str(path).strip():
            return
        key = _norm(path)
        if key not in seen:
            owner = personal_user(path)
            seen[key] = ({"path": str(path).strip(), "personal": bool(owner), "user": owner}, [])
            order.append(key)
        if who not in seen[key][1]:
            seen[key][1].append(who)

    screens = os.path.join(root, "screens")
    try:
        names = sorted(os.listdir(screens))
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(".json"):
            continue
        data = _read(os.path.join(screens, name))
        if not data or not data.get("screen"):
            continue
        add(data.get("output_dir"), data["screen"])
        for target in data.get("distribute_to") or []:
            add(target, data["screen"])
    batches = os.path.join(screens, "batches")
    try:
        names = sorted(os.listdir(batches))
    except OSError:
        names = []
    for name in names:
        data = _read(os.path.join(batches, name)) if name.lower().endswith(".json") else None
        if data:
            add(data.get("output_dir"), "@" + name[:-5])
    add(gmes_core.OUTPUT_DIR if root == HERE else os.path.join(root, "Data Hub Folder", "GMES"),
        "every report without a folder of its own")
    return [seen[k] for k in order]


SHARED_PROFILES = ("public", "default", "default user", "all users")


def long_path(path):
    r"""A path with Windows' 8.3 short names expanded (C:\Users\M06DE~1.LAB -> m.labib),
    as far as it exists; the rest is kept as written."""
    path = os.path.normpath(str(path).strip())
    head, tail = path, []
    while head and not os.path.exists(head) and os.path.dirname(head) != head:
        head, part = os.path.dirname(head), os.path.basename(head)
        tail.insert(0, part)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(head, buf, 32768)
        if 0 < n < 32768:
            head = buf.value
    except (ImportError, AttributeError, OSError):
        pass
    return os.path.join(head, *tail) if tail else head


def personal_user(path):
    r"""The Windows user whose OWN profile folder `path` is in (C:\Users\<name>\...), or ''.
    C:\Users\Public and the default profile are shared, not anyone's own."""
    m = PERSONAL.match(long_path(path))
    return m.group(1) if m and m.group(1).lower() not in SHARED_PROFILES else ""


def other_users_folder(path, profile=None):
    """The OTHER user (not the one running this) whose own folder `path` is in, or ''.
    Such a folder does not exist on another PC, and is not this account's to write to."""
    owner = personal_user(path)
    if not owner:
        return ""
    mine = _norm(long_path(profile or os.environ.get("USERPROFILE") or os.path.expanduser("~")))
    here = _norm(long_path(path))
    return "" if here == mine or here.startswith(mine + os.sep) else owner


def folder_state(path, write_test=True, timeout=FOLDER_TIMEOUT):
    """(status, words) for one folder. A network folder that does not answer must not
    hang the check, so the look runs in a thread with a time limit."""
    answer = {}

    def look():
        try:
            if os.path.isdir(path):
                if not write_test:
                    answer["r"] = (OK, "exists")
                    return
                probe = os.path.join(path, f"~gmes-write-test-{os.getpid()}.tmp")
                try:
                    with open(probe, "w", encoding="utf-8") as fh:
                        fh.write("test")
                    os.remove(probe)
                    answer["r"] = (OK, "exists, this Windows account can write to it")
                except OSError as e:
                    answer["r"] = (FAIL, f"this Windows account cannot write to it ({e.strerror or e})")
                return
            if os.path.exists(path):
                answer["r"] = (FAIL, "it is a file, not a folder")
                return
            parent = os.path.dirname(os.path.normpath(path))
            while parent and not os.path.isdir(parent) and os.path.dirname(parent) != parent:
                parent = os.path.dirname(parent)
            if parent and os.path.isdir(parent) and os.path.dirname(parent) != parent:
                answer["r"] = (WARN, f"does not exist yet - the first run creates it inside {parent}")
            elif parent and os.path.isdir(parent):
                answer["r"] = (WARN, "does not exist yet - the first run creates it")
            else:
                answer["r"] = (FAIL, "does not exist, and neither does the drive or network share")
        except OSError as e:
            answer["r"] = (FAIL, f"could not be read ({e.strerror or e})")

    t = threading.Thread(target=look, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return FAIL, f"no answer in {timeout} s - the network folder is unreachable from this PC"
    return answer.get("r", (FAIL, "could not be checked"))


def check_folders(root=None, write_test=True, profile=None):
    root = root or HERE
    me = os.environ.get("USERNAME") or "?"
    out = []
    for folder, who in pinned_folders(root):
        path = folder["path"]
        names = ", ".join(who[:6]) + (f" and {len(who) - 6} more" if len(who) > 6 else "")
        status, words = folder_state(path, write_test)
        fix = ""
        other = other_users_folder(path, profile) if folder["personal"] else ""
        if other:
            status = FAIL if status != OK else WARN
            words = f"a folder of the Windows user '{other}' (this is '{me}') - " + words
            fix = f'GMES_Workflow.bat move-folder "{path}" "<a folder on this PC>"'
        elif status == FAIL:
            fix = (f'make the folder reachable for this account, or: GMES_Workflow.bat move-folder '
                   f'"{path}" "<another folder>"')
        out.append(Result(status, path, f"{words}  [{names}]", fix))
    return out


# --------------------------------------------------------------------------
# What the tool knows
# --------------------------------------------------------------------------
def check_recordings():
    import gmes_profile
    import gmes_recordcheck as rc
    profiles = [p for p in gmes_profile.known() if isinstance(p, dict)]
    recorded = [p for p in profiles if p.get("learned")]
    out = [Result(OK if recorded else WARN, "Recordings",
                  f"{len(recorded)} recorded here, {len(profiles) - len(recorded)} structure only",
                  "" if recorded else "record a screen first: GMES_Workflow.bat record <CODE> ...")]
    for path, why in gmes_profile.unreadable():
        out.append(Result(FAIL, f"Recording {os.path.basename(path)}", f"cannot be read ({why})",
                          "record it again, or remove the file"))
    try:
        certs = rc.certificates()
    except OSError:
        certs = {}
    failed = sorted(c for c, v in certs.items() if v.get("verdict") == "FAILED")
    unchecked = sorted(str(p.get("screen", "")).upper() for p in recorded
                       if str(p.get("screen", "")).upper() not in certs)
    if failed:
        out.append(Result(WARN, "Record checks", f"the last check FAILED for {', '.join(failed)}",
                          "GMES_Workflow.bat check " + " ".join(failed)))
    if unchecked:
        out.append(Result(INFO, "Record checks", f"never checked on this PC: {', '.join(unchecked[:12])}"
                          + (" ..." if len(unchecked) > 12 else "")))
    return out


def check_batches():
    import gmes_batch
    import gmes_core as core
    batches = gmes_batch.list_batches()
    if not batches:
        return [Result(INFO, "Saved batches", "none yet - save one with: python gmes_batch.py save NAME ...")]
    out = []
    for name, b in sorted(batches.items(), key=lambda kv: kv[0].lower()):
        policy = str(b.get("date") or "yesterday")
        try:
            items = gmes_batch.build_plan(list(b.get("screens") or []), policy,
                                          core.effective_export(b.get("export")), b.get("output_dir"))
        except Exception as e:                               # noqa: BLE001
            out.append(Result(FAIL, f"Batch @{name}", f"cannot be planned: {e}",
                              f"python gmes_batch.py plan --batch {name}"))
            continue
        blocked = [f"{i.code} ({i.blocked})" for i in items if not i.ready]
        ready = sum(1 for i in items if i.ready)
        status = FAIL if not ready else (WARN if blocked else OK)
        detail = f"{ready} of {len(items)} ready, dates: {policy}"
        if blocked:
            detail += "; skipped: " + "; ".join(blocked[:4]) + (" ..." if len(blocked) > 4 else "")
        fix = f"python gmes_batch.py plan --batch {name}" if blocked else ""
        if policy.lower() not in FIXED_POLICIES and not re.fullmatch(r"-\d+", policy):
            status = WARN if status == OK else status
            detail += " - a FIXED date: every scheduled run exports that same day"
            fix = fix or f"python gmes_batch.py save {name} ... --date yesterday"
        out.append(Result(status, f"Batch @{name}", detail, fix))
    return out


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------
def snapshot(root=None):
    root = root or HERE
    data = _read(os.path.join(root, "schedules.json")) or {}
    return [s for s in data.get("schedules") or [] if isinstance(s, dict) and s.get("batch")], \
        data.get("from_pc", "")


def check_schedules(root=None, tasks=None, app_tasks=None):
    root = root or HERE
    import gmes_batch
    import gmes_schedule
    try:
        tasks = gmes_schedule.list_tasks() if tasks is None else tasks
        app_tasks = gmes_schedule.list_tasks("GMES_App_") if app_tasks is None else app_tasks
    except gmes_schedule.ScheduleError as e:
        return [Result(WARN, "Schedules", f"Task Scheduler could not be read ({e})", "try again in a minute")]
    batches = {n.lower() for n in gmes_batch.list_batches()}
    out = []
    for t in tasks:
        title = f"Schedule @{t['batch']}"
        when = t.get("when") or t.get("trigger") or "?"
        if t["batch"].lower() not in batches:
            out.append(Result(FAIL, title, f"{when} - but its batch does not exist here, so it fails every run",
                              f"save the batch '{t['batch']}' again, or remove the schedule"))
            continue
        other = gmes_schedule.runs_elsewhere(t)
        if other:
            out.append(Result(FAIL, title, f"{when} - it runs the copy of the tool in "
                                           f"{os.path.dirname(other)}, not this one",
                              f"python gmes_batch.py schedule {t['batch']} --at {t.get('at') or 'HH:MM'} "
                              "... (from THIS folder)"))
            continue
        notes = gmes_schedule.assess_task(t)
        last = t.get("last_text") or "not run yet"
        out.append(Result(WARN if notes else OK, title, f"{when}; next {t.get('next_run') or '-'}; last: {last}"
                          + (" - " + "; ".join(notes) if notes else "")))
    here = {t["batch"].lower() for t in tasks}
    window = {t["batch"].lower() for t in app_tasks}
    wanted, from_pc = snapshot(root)
    missing = [s for s in wanted if s["batch"].lower() not in here and s["batch"].lower() not in window]
    if missing:
        out.append(Result(WARN, "Schedules from the old PC",
                          f"{len(missing)} not set up here yet: "
                          + ", ".join(f"@{s['batch']} ({s.get('when') or s.get('at')})" for s in missing),
                          "GMES_Workflow.bat setup"))
    if app_tasks:
        out.append(Result(INFO, "GMES Automation's own schedules on this PC",
                          ", ".join(f"@{t['batch']} ({t.get('when') or '?'})" for t in app_tasks)))
    if not tasks and not missing:
        out.append(Result(INFO, "Schedules", "nothing is scheduled by this tool on this PC"))
    return out


# --------------------------------------------------------------------------
# Windows: will a schedule actually start?
# --------------------------------------------------------------------------
def _registry(path, name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except (ImportError, OSError):
        return None


def check_session(autologon=None, session=None, user=None):
    """A schedule of this tool runs only while its Windows user is signed in (the saved
    sign-in and the browser both need that session - gmes_schedule's docstring). On a
    server that is the one rule that matters most, and nothing else would say it."""
    user = user or os.environ.get("USERNAME") or "?"
    autologon = _registry(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "AutoAdminLogon") \
        if autologon is None else autologon
    session = os.environ.get("SESSIONNAME", "") if session is None else session
    out = []
    if str(autologon).strip() == "1":
        out.append(Result(OK, "After a restart", "Windows signs in by itself (automatic sign-in is on)"))
    else:
        out.append(Result(WARN, "After a restart",
                          f"nothing runs until '{user}' signs in to Windows again - a restart for Windows "
                          "Update at night stops every schedule until someone does",
                          "ask IT for automatic sign-in of this account on this server, or sign in "
                          "after every restart"))
    if session.upper().startswith("RDP"):
        out.append(Result(INFO, "Remote session", "when you leave, close the window or Disconnect - NEVER "
                                                  "'Sign out': signed out, the schedules do not run"))
    else:
        out.append(Result(INFO, "Leaving the PC", "lock it (Win+L) - never 'Sign out'"))
    return out


def check_sleep(query=None):
    """A PC that sleeps runs a batch late (when it wakes), not at its time."""
    try:
        text = query() if query else subprocess.run(
            ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return [Result(INFO, "Sleep", "the power settings could not be read")]
    m = re.search(r"AC Power Setting Index:\s*0x([0-9a-fA-F]+)", text or "")
    if not m:
        return [Result(INFO, "Sleep", "the power settings could not be read")]
    seconds = int(m.group(1), 16)
    if seconds == 0:
        return [Result(OK, "Sleep", "this PC never sleeps on mains power")]
    return [Result(WARN, "Sleep", f"this PC sleeps after {seconds // 60} minutes without use - a batch then "
                                  "runs late, when it wakes, not at its time",
                   "powercfg /change standby-timeout-ac 0   (never sleep on mains power)")]


def check_basics():
    import gmes_preflight
    out = []
    for name, check in gmes_preflight.CHECKS:
        try:
            ok, detail = check()
        except Exception as e:                               # noqa: BLE001
            ok, detail = False, f"the check itself failed: {e!r}"
        fix = ""
        if name == "Saved sign-in" and ok is not True:
            fix = "GMES_Workflow.bat setup   (or: python gmes_credentials.py set)"
        out.append(Result({True: OK, None: WARN, False: FAIL}[ok], name, detail, fix))
    return out


def check_twin():
    """On a PC that also has the window (GMES Automation): are the two level?
    (CLAUDE.md 0a). A server package has no window beside it - nothing to say then."""
    import gmes_twin
    report = gmes_twin.sync(dry_run=True)
    if report.skipped:
        return []
    out = [Result(OK if not report.actions else INFO, "Same recordings, batches and checks",
                  "level" if not report.actions else f"{len(report.actions)} item(s) to sync - each "
                                                      "tool syncs on its next start")]
    for kind, name, words in report.conflicts:
        out.append(Result(WARN, f"Not synced: {kind} {name}", words,
                          "save the batch once more in the tool that has it right, or rename one"))
    return out


# --------------------------------------------------------------------------
# The package itself
# --------------------------------------------------------------------------
def verify(root=None):
    """Every file the package was built with is here and unchanged. A tool file that
    differs is damage; a data file that differs is normal after the first runs."""
    root = root or HERE
    import gmes_package
    manifest = _read(os.path.join(root, "MANIFEST.json"))
    if manifest is None:
        return [Result(INFO, "Package", "this folder was not made by gmes_package.py (no MANIFEST.json)")]
    out, missing, damaged, changed, gone = [], [], [], [], []
    for rel, info in (manifest.get("files") or {}).items():
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(path):
            (gone if info.get("kind") == "data" else missing).append(rel)
            continue
        if gmes_package.sha256(path) != info.get("sha256"):
            (changed if info.get("kind") == "data" else damaged).append(rel)
    total = len(manifest.get("files") or {})
    if missing or damaged:
        if missing:
            out.append(Result(FAIL, "Package files missing", ", ".join(missing[:10])
                              + (" ..." if len(missing) > 10 else ""), "copy the package again"))
        if damaged:
            out.append(Result(FAIL, "Package files changed or damaged", ", ".join(damaged[:10])
                              + (" ..." if len(damaged) > 10 else ""), "copy the package again"))
    else:
        out.append(Result(OK, "Package", f"{manifest.get('package')}: all {total - len(changed) - len(gone)} files as built "
                                         f"on {manifest.get('built_on') or '?'} {manifest.get('built')}"))
    if gone:
        out.append(Result(WARN, "Package data missing", ", ".join(gone[:10]) + (" ..." if len(gone) > 10 else "")
                          + " - a recording or batch the package came with is not here",
                          "copy the package again, unless it was deleted here on purpose"))
    if changed:
        out.append(Result(INFO, "Package data", f"{len(changed)} data file(s) changed since it was built "
                                                "(normal once reports have run here)"))
    return out


# --------------------------------------------------------------------------
# The whole check
# --------------------------------------------------------------------------
SECTIONS = (
    ("This package", lambda o: verify()),
    ("This PC", lambda o: check_basics()),
    ("Windows - will a schedule start?", lambda o: check_session() + check_sleep()),
    ("What the tool knows", lambda o: check_recordings() + check_batches()),
    ("Where the reports are saved", lambda o: check_folders(write_test=o.get("write_test", True))),
    ("Schedules", lambda o: check_schedules()),
    ("GMES Automation beside it", lambda o: check_twin()),
)


def run_checks(options=None, sections=SECTIONS, show=print):
    options = options or {}
    results = []
    for title, fn in sections:
        try:
            part = fn(options)
        except Exception as e:                               # noqa: BLE001 - a broken check is a FAIL
            part = [Result(FAIL, title, f"the check itself failed: {type(e).__name__}: {e}")]
        results.extend(part)
        if show:
            show(f"\n{title}")
            for r in part:
                show(f"  [{MARK[r.status]}] {r.title}" + (f" - {r.detail}" if r.detail else ""))
    return results


def verdict(results):
    fails = [r for r in results if r.status == FAIL]
    warns = [r for r in results if r.status == WARN]
    if fails:
        return "NOT READY", fails, warns
    return (f"READY, WITH {len(warns)} WARNING{'S' if len(warns) > 1 else ''}" if warns else "READY"), fails, warns


def report(results, show=print):
    word, fails, warns = verdict(results)
    show("\n" + "=" * 78)
    show(f"{word}" + (f" - {len(fails)} problem(s) stop a night run" if fails else "")
         + (f", and {len(warns)} warning(s)" if fails and warns else ""))
    todo = [r for r in fails + warns if r.fix]
    if todo:
        show("\nWhat to do:")
        seen = set()
        n = 0
        for r in todo:
            if r.fix in seen:
                continue
            seen.add(r.fix)
            n += 1
            show(f"  {n}. {r.title}: {r.fix}")
    return 1 if fails else 0


# --------------------------------------------------------------------------
# Setup (asks before every change)
# --------------------------------------------------------------------------
def _yes(question, ask=input):
    try:
        return ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def schedules_to_create(root=None, tasks=None, app_tasks=None, batches=None):
    """(to create [snapshot entries], skipped [(entry, why)])."""
    root = root or HERE
    import gmes_batch
    import gmes_schedule
    tasks = gmes_schedule.list_tasks() if tasks is None else tasks
    app_tasks = gmes_schedule.list_tasks("GMES_App_") if app_tasks is None else app_tasks
    batches = {n.lower() for n in (gmes_batch.list_batches() if batches is None else batches)}
    here = {t["batch"].lower() for t in tasks}
    window = {t["batch"].lower() for t in app_tasks}
    todo, skipped, seen = [], [], set()
    for s in snapshot(root)[0]:
        key = s["batch"].lower()
        if key in seen:
            skipped.append((s, "named twice in schedules.json - the first one is used"))
            continue
        seen.add(key)
        site = (s.get("site") or "seeg").lower()
        if site != "seeg":
            # Another G-MES's batch (HISTORY.md Phase 130): created here it would become a
            # SEEG schedule of a SEEG batch that may not exist, or is a different one.
            skipped.append((s, f"a batch of the {site.upper()} G-MES - schedule it with: "
                               f"python gmes_batch.py schedule {s['batch']} --site {site} --at ..."))
        elif key in here:
            skipped.append((s, "already scheduled here"))
        elif key in window:
            skipped.append((s, "GMES Automation already schedules it on this PC - it would run twice"))
        elif key not in batches:
            skipped.append((s, "its batch is not in this package"))
        elif s.get("kind") == "once":
            skipped.append((s, "a one-time schedule - make it again if it is still wanted"))
        elif not s.get("at") or s.get("kind") not in ("daily", "weekly"):
            skipped.append((s, "its time could not be read on the old PC"))
        else:
            todo.append(s)
    return todo, skipped


def create_from_snapshot(entries, create=None, enable=None):
    import gmes_schedule
    create = create or gmes_schedule.create
    enable = enable or gmes_schedule.set_enabled
    done, failed = [], []
    for s in entries:
        when = gmes_schedule.When(s["at"], s["kind"], list(s.get("days") or []))
        try:
            create(s["batch"], when)
            if s.get("enabled") is False:
                enable(s["batch"], False)
            done.append(s)
        except (ValueError, gmes_schedule.ScheduleError) as e:
            failed.append((s, str(e)))
    return done, failed


def setup(ask=input, show=print, write_test=True):
    import gmes_credentials
    show("GMES TOOL - make this PC ready to run the batches by itself\n")
    for r in verify():
        show(f"  [{MARK[r.status]}] {r.title} - {r.detail}")
        if r.status == FAIL:
            show("\nThe package is not complete - copy it again before anything else.")
            return 1
    if not os.path.isfile(gmes_credentials.STORE_PATH):
        show(f"\nNo G-MES sign-in is saved for the Windows user '{os.environ.get('USERNAME', '?')}' on this PC.")
        show("(A saved sign-in never travels in a package: it is encrypted for one user on one PC.)")
        if _yes("Save it now?", ask):
            gmes_credentials.main("set")
    else:
        show("\n  [OK  ] A G-MES sign-in is saved for this Windows user (not read).")
    try:
        todo, skipped = schedules_to_create()
    except Exception as e:                                   # noqa: BLE001
        show(f"\n  [WARN] Task Scheduler could not be read ({e}) - no schedule was created")
        todo, skipped = [], []
    for s, why in skipped:
        show(f"  [ -  ] @{s['batch']} ({s.get('when') or s.get('at')}): {why}")
    if todo:
        show(f"\nThe package came with {len(todo)} schedule(s) that are not set up on this PC:")
        for s in todo:
            show(f"    @{s['batch']:<20} {s.get('when') or s['at']}" + ("   (paused)" if s.get("enabled") is False else ""))
        show(f"They will run as '{os.environ.get('USERNAME', '?')}', only while that user is signed in.")
        if _yes(f"Create these {len(todo)} schedule(s) now?", ask):
            done, failed = create_from_snapshot(todo)
            for s in done:
                show(f"  [OK  ] @{s['batch']} scheduled: {s.get('when') or s['at']}")
            for s, why in failed:
                show(f"  [FAIL] @{s['batch']}: {why}")
            if done:
                show("Prove one once, now, while you watch:  python gmes_batch.py run-scheduled "
                     + done[0]["batch"])
    show("\nThe check, after setup:")
    return report(run_checks({"write_test": write_test}, show=show), show=show)


# --------------------------------------------------------------------------
# move-folder: re-point what was pinned to a folder of the old PC
# --------------------------------------------------------------------------
def _moved(value, old, new):
    """`value` re-pointed from `old` to `new` (the folder itself or anything under it),
    or None when it is not under `old`."""
    if not value:
        return None
    v, o = _norm(value), _norm(old)
    if v == o:
        return new
    if v.startswith(o + os.sep):
        rest = os.path.normpath(str(value).strip())[len(os.path.normpath(str(old).strip().rstrip("\\/"))) + 1:]
        return os.path.join(new, rest)
    return None


def plan_move(old, new, root=None):
    """[(file, field, before, after)] - nothing is written."""
    root = root or HERE
    changes = []
    screens = os.path.join(root, "screens")
    for folder, fields in ((screens, ("output_dir", "distribute_to")),
                           (os.path.join(screens, "batches"), ("output_dir",))):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            data = _read(path) if name.lower().endswith(".json") and os.path.isfile(path) else None
            if not data:
                continue
            for field in fields:
                value = data.get(field)
                if isinstance(value, list):
                    for item in value:
                        after = _moved(item, old, new)
                        if after:
                            changes.append((path, field, item, after))
                else:
                    after = _moved(value, old, new)
                    if after:
                        changes.append((path, field, value, after))
    return changes


def apply_move(changes, old, new, now=None, root=None):
    """Write the changes; every file is backed up first (screens/.backup/<time>/) and
    replaced in one step. Returns the backup folder."""
    root = root or HERE
    import shutil
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(root, "screens", ".backup", f"move-folder_{stamp}")
    files = sorted({c[0] for c in changes})
    for path in files:
        data = _read(path)
        if data is None:
            continue
        rel = os.path.relpath(path, os.path.join(root, "screens"))
        os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
        shutil.copy2(path, os.path.join(backup, rel))
        for field in ("output_dir", "distribute_to"):
            value = data.get(field)
            if isinstance(value, list):
                data[field] = [(_moved(v, old, new) or v) for v in value]
            elif value:
                data[field] = _moved(value, old, new) or value
        with open(path + ".partial", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(path + ".partial", path)
    return backup


def move_folder(old, new, yes=False, ask=input, show=print):
    if _norm(old) == _norm(new):
        show("The old and the new folder are the same - nothing to do.")
        return 2
    changes = plan_move(old, new)
    if not changes:
        show(f"No recording or batch saves to {old} (or a folder inside it) - nothing to change.")
        return 0
    show(f"These would save to {new} instead:")
    for path, field, before, after in changes:
        what = {"output_dir": "saves to", "distribute_to": "also copies to"}[field]
        show(f"  {os.path.basename(path)[:-5]:<14} {what:<15} {before}\n  {'':<14} {'now':<15} {after}")
    status, words = folder_state(new, write_test=True)
    show(f"\nThe new folder: {words}")
    if status == FAIL:
        show("Choose a folder this Windows account can write to - nothing was changed.")
        return 1
    if not yes and not _yes(f"Change {len({c[0] for c in changes})} file(s)?", ask):
        show("Nothing was changed.")
        return 0
    backup = apply_move(changes, old, new)
    show(f"Changed. The files as they were are kept in {backup}")
    return 0


# --------------------------------------------------------------------------
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].lower() == "server":             # GMES_Workflow.bat server
        argv = argv[1:]
    command = (argv[0].lower() if argv else "check")
    if command in ("help", "-h", "--help", "/?"):
        print(HELP)
        return 0
    if command == "verify":
        results = verify()
        for r in results:
            print(f"  [{MARK[r.status]}] {r.title} - {r.detail}")
        return 1 if any(r.status == FAIL for r in results) else 0
    if command == "move-folder":
        p = argparse.ArgumentParser(prog="gmes_server.py move-folder")
        p.add_argument("old")
        p.add_argument("new")
        p.add_argument("--yes", action="store_true")
        a = p.parse_args(argv[1:])
        return move_folder(a.old, os.path.abspath(a.new) if not a.new.startswith("\\\\") else a.new, a.yes)
    write_test = "--no-write-test" not in argv
    if command == "setup":
        return setup(write_test=write_test)
    if command not in ("check", "--no-write-test"):
        print(f"Unknown command '{command}'.\n")
        print(HELP)
        return 2
    print(f"GMES TOOL - is this PC ready to run the batches by itself?  ({HERE})")
    if not write_test:
        print("(folders are NOT write-tested)")
    return report(run_checks({"write_test": write_test}))


if __name__ == "__main__":
    sys.exit(main())
