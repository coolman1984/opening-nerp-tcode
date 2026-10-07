"""The two front ends stay at the same level: GMES_Workflow.bat (the command line) and
GMES_Automation.exe (the window). CLAUDE.md section 0a.

They are two windows on ONE engine (the flat modules; GMES/app/engine holds byte-identical
copies). What they must also share is what each one LEARNS:

    recordings      screens/*.json                  <-> GMES/data/screens/*.json
    saved batches   screens/batches/*.json          <-> GMES/data/screens/batches/*.json
    certificates    screens/certificates/*.json     <-> GMES/data/certificates/*.json
    confirmations   screens/confirmations.json      <-> GMES/data/confirmations.json
    run history     logs/batches/batch_*            <-> GMES/data/logs/batches/batch_*

Until HISTORY.md Phase 123 nothing joined them: the window re-recorded all 35 screens
on 2026-10-06 and recorded two new ones, and the command line kept replaying the old
recordings without knowing.

`sync()` is a THREE-WAY sync against what both sides held after the last sync
(screens/.twin/state.json):
  - changed on one side only        -> copied to the other
  - new on one side                 -> copied to the other
  - removed on one side, unchanged  -> removed on the other too (a recording the person
    on the other                       chose to Forget stays forgotten) - MOVED into
                                       screens/.twin/backup/<time>/, never deleted
  - changed on BOTH sides           -> a recording: the newer `learned` wins, the other
                                       is kept in the backup; a batch: NOT touched, the
                                       conflict is reported for a person to decide
    (a batch is someone's intent under a name; picking one silently would change
    what a schedule runs)
  - certificates and run reports are written once and never edited: copied both ways,
    never removed
  - confirmations: per screen, the newer one wins

Nothing is ever deleted (CLAUDE.md 2.1a: additive, recoverable). A file being written
at that moment is safe: every writer here replaces its file atomically.

    python gmes_twin.py status          what differs, changes nothing
    python gmes_twin.py sync            make both sides the same
    python gmes_twin.py import FOLDER   bring <CODE>.json recordings from another PC
    python gmes_twin.py parity          what the window does, and the command for it here
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime

# Set by GMES/app/app_env.py inside the window: the project root it sits in (or None when
# the GMES folder was handed to another PC on its own - then there is no twin) and its own
# data folder. Unset, the twin is derived from where this file is: the project root.
CLI_ROOT = None
EXE_DATA = None
CONFIGURED = False

LOCK_STALE_SECONDS = 120
CODE_PATTERN = r"(?=[A-Za-z0-9]*\d)[A-Za-z][A-Za-z0-9]{4,15}"     # = gmes_profile.CODE_PATTERN
BATCH_NAME = r"[A-Za-z0-9_-]{1,40}"                                  # = gmes_batch._NAME

# kind, path on the command line's side, path on the window's side, which files, strategy
KINDS = (
    ("recordings", ("screens",), ("screens",), rf"{CODE_PATTERN}\.json", "newest"),
    ("batches", ("screens", "batches"), ("screens", "batches"), rf"{BATCH_NAME}\.json", "ask"),
    ("certificates", ("screens", "certificates"), ("certificates",), r"[A-Za-z0-9_]+\.json", "union"),
    ("run reports", ("logs", "batches"), ("logs", "batches"),
     r"batch_[0-9_]+(\.json|\.txt|_summary\.html)", "union"),
)
CONFIRMATIONS = (("screens", "confirmations.json"), ("confirmations.json",))


def is_project_root(path):
    return bool(path) and os.path.isfile(os.path.join(path, "gmes_core.py")) and \
        os.path.isfile(os.path.join(path, "GMES_Workflow.bat"))


def pair():
    """(command-line root, window data folder), or None when this copy has no twin.
    GMES_TWIN=off switches it off (the offline test suites set it: a test must never
    sync into the person's real recordings)."""
    if os.environ.get("GMES_TWIN", "").strip().lower() in ("off", "0", "no"):
        return None
    if CONFIGURED:
        return (CLI_ROOT, EXE_DATA) if CLI_ROOT and EXE_DATA else None
    # GMES_TWIN_CLI_ROOT / GMES_TWIN_EXE_DATA point the twin elsewhere - the test suites
    # aim both at a temporary folder as a SECOND guard, so even a broken "off" switch
    # cannot reach the real recordings (HISTORY.md Phase 123.3: a mutation that broke it
    # did exactly that).
    if os.environ.get("GMES_TWIN_CLI_ROOT"):
        return os.environ["GMES_TWIN_CLI_ROOT"], os.environ.get("GMES_TWIN_EXE_DATA") or \
            os.path.join(os.environ["GMES_TWIN_CLI_ROOT"], "GMES", "data")
    here = os.path.dirname(os.path.abspath(__file__))
    if not is_project_root(here) or not os.path.isdir(os.path.join(here, "GMES", "app")):
        return None
    return here, os.environ.get("GMES_TWIN_EXE_DATA") or os.path.join(here, "GMES", "data")


# --------------------------------------------------------------------------
# Reading one side
# --------------------------------------------------------------------------
def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _files(folder, pattern):
    """{lower-case name: (path, sha)} - Windows names ignore case ('Test' = 'test')."""
    out = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    rx = re.compile(pattern + r"\Z")
    for n in names:
        full = os.path.join(folder, n)
        if rx.match(n) and os.path.isfile(full):
            try:
                out[n.lower()] = (full, _sha(full))
            except OSError:
                continue
    return out


def _json(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _batch_meaning(path):
    """What a batch DOES - two files that differ only in when they were saved are equal."""
    data = _json(path) or {}
    return json.dumps({k: data.get(k) for k in ("screens", "date", "export", "output_dir")},
                      sort_keys=True)


# --------------------------------------------------------------------------
# The sync
# --------------------------------------------------------------------------
class Report:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.actions = []           # (kind, name, words)
        self.conflicts = []         # (kind, name, words)
        self.skipped = ""           # why nothing was done at all

    def did(self, kind, name, words):
        self.actions.append((kind, name, words))

    def conflict(self, kind, name, words):
        self.conflicts.append((kind, name, words))

    @property
    def in_sync(self):
        return not self.actions and not self.conflicts and not self.skipped

    def lines(self):
        if self.skipped:
            return [self.skipped]
        out = []
        for kind, name, words in self.actions:
            out.append(f"  {kind:<13} {name:<34} {words}")
        for kind, name, words in self.conflicts:
            out.append(f"  CONFLICT {kind:<8} {name:<34} {words}")
        head = ("The command line and the window are at the same level." if self.in_sync else
                f"{'Would change' if self.dry_run else 'Synced'} {len(self.actions)} item(s)"
                + (f", {len(self.conflicts)} conflict(s) for a person to decide" if self.conflicts else ""))
        return [head] + out


class _Sync:
    def __init__(self, cli_root, exe_data, dry_run, now, scheduled):
        self.sides = {"cli": cli_root, "exe": exe_data}
        self.dry = dry_run
        self.report = Report(dry_run)
        self.stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
        self.twin_dir = os.path.join(cli_root, "screens", ".twin")
        self.state_path = os.path.join(self.twin_dir, "state.json")
        self.state = (_json(self.state_path) or {}) if not dry_run else dict(_json(self.state_path) or {})
        self.scheduled = scheduled
        self._scheduled_names = None

    # ---- actions -----------------------------------------------------------
    def _backup(self, side, kind, path):
        dest = os.path.join(self.twin_dir, "backup", self.stamp, side, kind.replace(" ", "_"))
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, os.path.basename(path))
        shutil.copy2(path, target)
        return target

    def _copy(self, kind, src, dst_folder, existing=None, name=None):
        """src -> the other side; `existing` (that side's own file, any case) is backed
        up first and replaced in place, so a name keeps the spelling it has there."""
        dst = existing or os.path.join(dst_folder, name or os.path.basename(src))
        if self.dry:
            return dst
        os.makedirs(dst_folder, exist_ok=True)
        if existing:
            self._backup(self._side_of(existing), kind, existing)
        tmp = dst + ".twin-partial"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        return dst

    def _retire(self, kind, path):
        """Removed on the other side: move it to the backup (never deleted)."""
        if self.dry:
            return
        self._backup(self._side_of(path), kind, path)
        os.remove(path)

    def _side_of(self, path):
        exe = os.path.normcase(os.path.abspath(self.sides["exe"]))
        return "exe" if os.path.normcase(os.path.abspath(path)).startswith(exe) else "cli"

    def _is_scheduled(self, name):
        if self._scheduled_names is None:
            try:
                self._scheduled_names = {n.lower() for n in (self.scheduled or scheduled_batches)()}
            except Exception:                                   # noqa: BLE001 - unsure = keep it
                self._scheduled_names = None
                return True
        return name.lower() in self._scheduled_names

    # ---- one kind -----------------------------------------------------------
    def kind(self, kind, cli_rel, exe_rel, pattern, strategy):
        folders = {"cli": os.path.join(self.sides["cli"], *cli_rel),
                   "exe": os.path.join(self.sides["exe"], *exe_rel)}
        files = {s: _files(f, pattern) for s, f in folders.items()}
        words = {"cli": "the command line", "exe": "the window"}
        for key in sorted(set(files["cli"]) | set(files["exe"])):
            a, b = files["cli"].get(key), files["exe"].get(key)
            skey = f"{kind}/{key}"
            base = self.state.get(skey)
            if strategy == "union":
                if a and not b:
                    self._copy(kind, a[0], folders["exe"])
                    self.report.did(kind, os.path.basename(a[0]), "copied to the window")
                elif b and not a:
                    self._copy(kind, b[0], folders["cli"])
                    self.report.did(kind, os.path.basename(b[0]), "copied to the command line")
                continue
            name = os.path.basename((a or b)[0])
            if a and b:
                if a[1] == b[1] or (strategy == "ask" and _batch_meaning(a[0]) == _batch_meaning(b[0])):
                    self.state[skey] = a[1]
                    continue
                if base == a[1]:
                    self._copy(kind, b[0], folders["cli"], existing=a[0])
                    self.state[skey] = b[1]
                    self.report.did(kind, name, "changed in the window - copied to the command line")
                elif base == b[1]:
                    self._copy(kind, a[0], folders["exe"], existing=b[0])
                    self.state[skey] = a[1]
                    self.report.did(kind, name, "changed in the command line - copied to the window")
                elif strategy == "newest":
                    la = str((_json(a[0]) or {}).get("learned") or "")
                    lb = str((_json(b[0]) or {}).get("learned") or "")
                    if la == lb:
                        self.report.conflict(kind, name, f"both sides hold a different recording learned "
                                                         f"at {la or '?'} - record it again in one of them")
                        continue
                    win, lose, to = (a, b, "exe") if la > lb else (b, a, "cli")
                    self._copy(kind, win[0], folders[to], existing=lose[0])
                    self.state[skey] = win[1]
                    self.report.did(kind, name, f"newer in {words['cli' if to == 'exe' else 'exe']} "
                                                f"({max(la, lb)} over {min(la, lb)}) - the older is kept "
                                                "in the backup")
                else:
                    self.report.conflict(kind, name, f"saved differently in both tools "
                                                     f"({_describe_batch(a[0])} | {_describe_batch(b[0])}) - "
                                                     "save it once more in the one that is right, or rename one")
                continue
            have, side = (a, "cli") if a else (b, "exe")
            other = "exe" if side == "cli" else "cli"
            if base and base == have[1]:
                if strategy == "ask" and self._is_scheduled(os.path.splitext(name)[0]):
                    self.report.conflict(kind, name, f"deleted in {words[other]} but still scheduled - "
                                                     "remove its schedule first, or save it there again")
                    continue
                self._retire(kind, have[0])
                self.state.pop(skey, None)
                self.report.did(kind, name, f"removed in {words[other]} - removed here too (kept in the backup)")
            else:
                self._copy(kind, have[0], folders[other], name=name)
                self.state[skey] = have[1]
                self.report.did(kind, name, f"new in {words[side]} - copied to {words[other]}")

    def confirmations(self):
        paths = {"cli": os.path.join(self.sides["cli"], *CONFIRMATIONS[0]),
                 "exe": os.path.join(self.sides["exe"], *CONFIRMATIONS[1])}
        data = {s: _json(p) or {} for s, p in paths.items()}
        merged = dict(data["cli"])
        for code, entry in data["exe"].items():
            mine = merged.get(code)
            if not isinstance(mine, dict) or str((entry or {}).get("at", "")) > str(mine.get("at", "")):
                merged[code] = entry
        for side, path in paths.items():
            if data[side] == merged:
                continue
            changed = sorted(c for c in merged if data[side].get(c) != merged[c])
            self.report.did("confirmations", ", ".join(changed)[:34] or "-",
                            f"brought to {'the command line' if side == 'cli' else 'the window'}")
            if not self.dry:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".twin-partial", "w", encoding="utf-8") as fh:
                    json.dump(merged, fh, indent=2)
                os.replace(path + ".twin-partial", path)

    def save_state(self):
        if self.dry:
            return
        os.makedirs(self.twin_dir, exist_ok=True)
        with open(self.state_path + ".partial", "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, indent=1, sort_keys=True)
        os.replace(self.state_path + ".partial", self.state_path)


def _describe_batch(path):
    data = _json(path) or {}
    return f"{len(data.get('screens') or [])} screens, {data.get('date', '?')}"


def scheduled_batches():
    """Names of the batches a scheduled task of EITHER front end runs (GMES_Batch_*,
    GMES_App_*). Raises when Task Scheduler cannot be read - the caller keeps the batch."""
    import gmes_schedule
    rc, out, err = gmes_schedule._run_powershell(
        "Get-ScheduledTask -TaskName 'GMES_*' -ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.TaskName }")
    if rc != 0:
        raise RuntimeError(err or out or "Task Scheduler could not be read")
    names = []
    for line in (out or "").splitlines():
        m = re.match(r"GMES_(?:Batch|App)_(.+)$", line.strip())
        if m:
            names.append(m.group(1))
    return names


class _Lock:
    """One sync at a time across both programs (a file created exclusively)."""

    def __init__(self, folder):
        self.path = os.path.join(folder, "sync.lock")
        self.held = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE_SECONDS:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                return self
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass


def sync(cli_root=None, exe_data=None, dry_run=False, now=None, scheduled=None):
    """Bring both front ends to the same level. Returns a Report (never raises for a
    single unreadable file; a missing twin is a Report with `skipped` set)."""
    if cli_root is None or exe_data is None:
        found = pair()
        if not found:
            r = Report(dry_run)
            r.skipped = "No twin here: this copy runs on its own (no project folder beside it)."
            return r
        cli_root, exe_data = found
    if os.path.normcase(os.path.abspath(cli_root)) == os.path.normcase(os.path.abspath(exe_data)):
        r = Report(dry_run)
        r.skipped = "The command line and the window use the same folder - nothing to sync."
        return r
    job = _Sync(cli_root, exe_data, dry_run, now, scheduled)
    with _Lock(job.twin_dir) as lock:
        if not lock.held:
            job.report.skipped = "Another sync is running right now - nothing done this time."
            return job.report
        for kind in KINDS:
            job.kind(*kind)
        job.confirmations()
        job.save_state()
    return job.report


def sync_quietly(log=None, **kwargs):
    """What a program calls on start and after a change: sync, say only what changed,
    never stop the program over it."""
    try:
        report = sync(**kwargs)
    except Exception as e:                                       # noqa: BLE001
        if log:
            log(f"  note: the window and the command line could not be synced ({e})")
        return None
    if log and (report.actions or report.conflicts):
        for line in report.lines():
            log(line)
    return report


class Announcer:
    """For a program that syncs again and again (the interactive tool before every
    Home, the window after every task): every change is said, a conflict only when
    it is new - the same unresolved conflict on every screen teaches people to stop
    reading the line."""

    def __init__(self, log):
        self.log = log
        self.said = None

    def __call__(self, **kwargs):
        report = sync_quietly(**kwargs)
        if report is None or report.skipped:
            return report
        for kind, name, words in report.actions:
            self.log(f"Synced with {'the command line' if CONFIGURED else 'the window'}: "
                     f"{kind} {name} - {words}")
        conflicts = sorted(report.conflicts)
        if conflicts and conflicts != self.said:
            for kind, name, words in conflicts:
                self.log(f"Not synced - {kind} {name}: {words}")
        self.said = conflicts
        return report


# --------------------------------------------------------------------------
# Recordings from another PC (the window's "Import recordings")
# --------------------------------------------------------------------------
def import_recordings(folder, target):
    """Copy recordings (<CODE>.json made by the command line or another copy of the
    window) into `target`. Never overwrites a newer recording, never takes a file
    whose content is another screen's recording (it would replay under the wrong code)."""
    done, skipped = [], []
    os.makedirs(target, exist_ok=True)
    rx = re.compile(CODE_PATTERN + r"\Z")
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or not rx.match(name[:-5]):
            continue
        src, dst = os.path.join(folder, name), os.path.join(target, name)
        data = _json(src)
        if data is None:
            skipped.append(f"{name}: unreadable" if os.path.isfile(src) else f"{name}: not a file")
            continue
        if not data.get("screen"):
            skipped.append(f"{name}: not a recording")
            continue
        if re.sub(r"\s+", "", str(data["screen"])).upper() != name[:-5].upper():
            skipped.append(f"{name}: it is the recording of {data['screen']}, not {name[:-5]}")
            continue
        if os.path.isfile(dst):
            mine = _json(dst)
            if isinstance(mine, dict) and str(mine.get("learned", "")) >= str(data.get("learned", "")):
                skipped.append(f"{name}: the one here is the same or newer")
                continue
        shutil.copyfile(src, dst)
        done.append(name[:-5])
    return done, skipped


# --------------------------------------------------------------------------
# Parity: everything the window does, and where the command line does it
# --------------------------------------------------------------------------
# (feature, the window's API names, the command line's ways). A CLI way is
#   "script.py word"   the word is a command/subcommand/flag of that script
#   "menu:key"         an item of the interactive tool's Home menu (GMES_Workflow.bat)
# tests/test_legacy_entrance.py fails when the window gains an API call that is in
# neither PARITY nor WINDOW_ONLY, and when a CLI way here does not exist.
PARITY = (
    ("Saved reports: status, last run, record check", ("get_library",),
     ("menu:saved_reports", "gmes_report.py status")),
    ("Run one report (as recorded / yesterday / today)", ("task:batch",),
     ("menu:run_saved", "gmes_report.py run", "gmes_batch.py run")),
    ("Find a screen in the catalogue", ("task:find",), ("gmes_report.py find",)),
    ("Describe a screen", ("task:describe",), ("gmes_report.py describe",)),
    ("Check the scope before anything runs", ("post_spec",), ("gmes_report.py record",)),
    ("Dry run (apply, stop before Inquiry)", ("task:record",), ("gmes_report.py --dry-run",)),
    ("Record + record check (bare replay, judged, certificate)", ("task:record",),
     ("menu:new_report", "gmes_report.py record")),
    ("Record check of an earlier recording", ("task:recheck",),
     ("menu:saved_reports", "gmes_report.py check")),
    ("Confirm a typed period seen on the G-MES screen", ("post_confirm",),
     ("gmes_report.py confirm",)),
    ("Forget a recording", ("post_forget",), ("gmes_report.py forget",)),
    ("Import recordings from another PC", ("post_import",), ("gmes_twin.py import",)),
    ("Plan a batch (what would run, and why not)", ("post_plan",), ("gmes_batch.py plan",)),
    ("Saved batches", ("get_batches", "post_batch_save", "post_batch_delete"),
     ("menu:report_group", "gmes_batch.py save", "gmes_batch.py batches", "gmes_batch.py delete")),
    ("Schedules: list, create, run now, pause/resume, delete",
     ("get_schedules", "post_when", "task:schedule_create", "task:schedule_run", "task:schedule_pause",
      "task:schedule_resume", "task:schedule_delete"),
     ("menu:schedules", "gmes_batch.py schedule", "gmes_batch.py schedules",
      "gmes_batch.py run-scheduled", "gmes_batch.py unschedule")),
    ("Row export: one Excel per row of a list", ("get_rowexport", "task:rowexport_load",
                                                 "task:rowexport_start", "post_rowexport_pause"),
     ("menu:row_export", "gmes_rowexport.py --load-only", "gmes_rowexport.py --start-row")),
    ("History: run reports and summaries", ("get_history",), ("menu:recent",)),
    ("Self-test", ("task:selftest",), ("gmes_preflight.py", "gmes_twin.py status")),
    ("Support package", ("task:support",), ("menu:settings",)),
    ("Account: the person's own login", ("get_account", "post_login", "post_login_check"),
     ("gmes_credentials.py set", "gmes_credentials.py test")),
    ("Browser choice (Automatic / Chrome / Edge)", ("post_browser",), ("gmes_browsers.py GMES_BROWSER",)),
    ("Test sign-in", ("task:test_signin",), ("gmes_connect.py",)),
)

# The window's own plumbing - nothing a command line needs an equivalent of.
WINDOW_ONLY = {
    "get_state": "the page's own status bar",
    "get_events": "the page's live Activity feed (a terminal prints as it goes)",
    "get_settings": "themes, fonts, text size, panel sizes",
    "post_settings": "themes, fonts, text size, panel sizes",
    "post_stop": "the red Stop button (Ctrl+C in a terminal)",
    "post_open": "open a folder from the window (the terminal prints the path)",
    "post_pick_folder": "the Windows folder picker (a terminal takes a typed path)",
}


def parity_lines():
    out = []
    for feature, exe, cli in PARITY:
        out.append(f"{feature}")
        out.append(f"    window : {', '.join(exe)}")
        out.append(f"    command: {', '.join(cli)}")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "status"
    if command == "parity":
        print("\n".join(parity_lines()))
        return 0
    if command == "import":
        if len(argv) < 2 or not os.path.isdir(argv[1]):
            print("usage: python gmes_twin.py import FOLDER   (a folder holding <CODE>.json files)")
            return 2
        import gmes_profile
        done, skipped = import_recordings(argv[1], gmes_profile.SCREENS_DIR)
        print(f"Imported {len(done)} recording(s): {', '.join(done) or '-'}")
        for s in skipped:
            print(f"  not imported: {s}")
        report = sync()
        print("\n".join(report.lines()))
        return 0
    if command not in ("status", "sync"):
        print(__doc__)
        return 2
    report = sync(dry_run=command == "status")
    print("\n".join(report.lines()))
    if command == "status" and not report.in_sync and not report.skipped:
        print("Run:  python gmes_twin.py sync")
    return 1 if report.conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
