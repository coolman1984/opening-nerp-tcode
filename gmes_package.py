"""Make ONE folder (and a .zip of it) holding everything the command-line tool needs -
to move it to a server, or to another PC - and nothing it does not.

    python gmes_package.py                  dist\\GMES_Tool_<time>\\ and dist\\GMES_Tool_<time>.zip
    python gmes_package.py --no-data        the tool only - no recordings, batches, checks
    python gmes_package.py --to E:\\handover put it somewhere else

WHAT GOES IN
  - every module the tool's entrances reach, found by following their imports (never a
    hand-kept list: a module someone forgets to list is the night that fails with
    "No module named ..."), plus GMES_Workflow.bat and requirements.txt;
  - screens_known\\ (the screen structures every user gets);
  - unless --no-data, what THIS PC has learned: screens\\*.json (recordings),
    screens\\batches\\, screens\\certificates\\, screens\\confirmations.json and the
    Row export form - after a sync with GMES Automation (CLAUDE.md 0a), so the newest
    recordings travel;
  - schedules.json: the schedules of this PC (when each batch runs), so
    `gmes_server.py setup` can create the same ones on the server;
  - MANIFEST.json: every file with its size and SHA-256, so `gmes_server.py verify`
    proves on the server that nothing was lost or damaged on the way;
  - START_HERE.txt and the guides.

WHAT NEVER GOES IN
  the saved sign-in (credentials.dat is encrypted for ONE Windows user on ONE PC - it
  cannot work anywhere else), the browser profile (bound to this machine), logs,
  exported files, the schedule launchers (they name this PC's Python and folder),
  the tests, the GMES Automation window, Mr.Samir, git history.

The package holds production data (filter values, folder names) when data is included:
move it the way you would move any work file, never put it in git (CLAUDE.md 2.4).
Built in a `.partial` folder and renamed only when complete, so a failed or stopped build
never leaves something that looks like a finished package.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_NAME = "GMES_Tool"

# Where a person or a schedule starts the tool; everything they import comes along.
ENTRANCES = ("run_gmes_workflow", "gmes_report", "gmes_batch", "gmes_schedule", "gmes_rowexport",
             "gmes_twin", "gmes_preflight", "gmes_credentials", "gmes_server", "gmes_package",
             "gmes_daily_prodplan",
             # the read-only inspection tools (CLAUDE.md 4.2) - for whoever supports the server
             "gmes_inspect", "gmes_find", "gmes_dump", "gmes_data", "gmes_connect",
             "gmes_open_screen", "gmes_probe_nexacro")
TOOL_FILES = ("GMES_Workflow.bat", "requirements.txt")
GUIDES = ("SERVER.md", "README.md", "AGENT_PLAYBOOK.md", "GMES_SKILL.md")
DATA_PARTS = (("screens", r"[A-Za-z][A-Za-z0-9]*\d[A-Za-z0-9]*\.json"),     # recordings
              (os.path.join("screens", "batches"), r"[A-Za-z0-9_-]{1,40}\.json"),
              (os.path.join("screens", "certificates"), r"[A-Za-z0-9_]+\.json"))
DATA_FILES = (os.path.join("screens", "confirmations.json"), os.path.join("screens", "rowexport.json"))
IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)

START_HERE = """GMES TOOL - the command-line G-MES automation, packaged {built}
========================================================================

1. Put this folder somewhere short and local, e.g.  C:\\gmes  (not OneDrive, not
   Desktop, not a network drive).
2. Install Python 3.10+ from python.org (NOT the Microsoft Store one), then once:
       python -m pip install -r requirements.txt
3. Prove nothing was lost on the way:
       GMES_Workflow.bat verify
4. Make it ready - it checks everything a night run needs, asks for YOUR G-MES
   sign-in (it cannot travel: it is encrypted for one Windows user on one PC) and
   offers to create the same schedules this package came with:
       GMES_Workflow.bat setup
5. Any time after:
       GMES_Workflow.bat server       is the server ready for tonight?
       GMES_Workflow.bat              the menu (run, record, batches, schedules ...)
       GMES_Workflow.bat help         every command on one screen

Read SERVER.md before the first night. The one rule a server must keep: the
Windows user the schedules belong to stays SIGNED IN (lock the session or
disconnect a remote session - never "Sign out"), or nothing runs.
"""


class PackageError(RuntimeError):
    pass


def closure(root=HERE, seeds=ENTRANCES):
    """Every module of `root` reachable from `seeds` by an import line (any depth,
    imports inside functions included)."""
    known = {n[:-3] for n in os.listdir(root) if n.endswith(".py")}
    todo, seen = [s for s in seeds if s in known], set()
    while todo:
        name = todo.pop()
        if name in seen or name not in known:
            continue
        seen.add(name)
        with open(os.path.join(root, name + ".py"), encoding="utf-8") as fh:
            todo.extend(IMPORT_RE.findall(fh.read()))
    return sorted(seen)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(root=HERE, with_data=True):
    """[(source path, path inside the package, kind)] - kind is 'tool', 'guide' or 'data'."""
    items = []
    missing = [s for s in ENTRANCES if not os.path.isfile(os.path.join(root, s + ".py"))
               and s not in ("gmes_probe_nexacro",)]
    if missing:
        raise PackageError(f"these entrances are missing from {root}: {', '.join(missing)}")
    for name in closure(root):
        items.append((os.path.join(root, name + ".py"), name + ".py", "tool"))
    for name in TOOL_FILES:
        src = os.path.join(root, name)
        if not os.path.isfile(src):
            raise PackageError(f"{name} is missing from {root}")
        items.append((src, name, "tool"))
    shipped = os.path.join(root, "screens_known")
    if os.path.isdir(shipped):
        for name in sorted(os.listdir(shipped)):
            if name.endswith(".json"):
                items.append((os.path.join(shipped, name), os.path.join("screens_known", name), "tool"))
    for name in GUIDES:
        if os.path.isfile(os.path.join(root, name)):
            items.append((os.path.join(root, name), name, "guide"))
    if with_data:
        for folder, pattern in DATA_PARTS:
            full = os.path.join(root, folder)
            if not os.path.isdir(full):
                continue
            rx = re.compile(pattern + r"\Z")
            for name in sorted(os.listdir(full)):
                if rx.match(name) and os.path.isfile(os.path.join(full, name)):
                    items.append((os.path.join(full, name), os.path.join(folder, name), "data"))
        for rel in DATA_FILES:
            if os.path.isfile(os.path.join(root, rel)):
                items.append((os.path.join(root, rel), rel, "data"))
    return items


def schedule_snapshot():
    """This PC's schedules (both front ends'), as {batch, when, from} - so the server can
    have the same ones. Never raises: a PC whose Task Scheduler cannot be read packages
    no schedules, and says so."""
    import gmes_schedule
    out, problem = [], ""
    for prefix, source in ((gmes_schedule.PREFIX, "command line"), ("GMES_App_", "GMES Automation")):
        try:
            for t in gmes_schedule.list_tasks(prefix):
                out.append({"batch": t["batch"], "at": t.get("at"), "kind": t.get("kind"),
                            "days": t.get("days") or [], "when": t.get("when"),
                            "enabled": str(t.get("state", "")).lower() != "disabled", "from": source})
        except Exception as e:                               # noqa: BLE001
            problem = f"Task Scheduler could not be read ({e}) - no schedules were packaged"
    return out, problem


def personal_folders(root=HERE, with_data=True):
    """Pinned folders that name a Windows user's own profile (C:\\Users\\<name>\\...):
    they exist on THIS PC only, so a run on a server would fail there or write into an
    odd place. Returned so the build can say it; `gmes_server.py move-folder` fixes it."""
    import gmes_server
    return gmes_server.pinned_folders(root) if with_data else []


def git_commit(root=HERE):
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                           text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return (r.stdout.strip() + (" + uncommitted changes" if dirty else "")) if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def build(dest_root=None, with_data=True, root=HERE, now=None, log=print, snapshot=None, sync=True,
          make_zip=True):
    """Build the package. Returns (folder, zip path or None, manifest)."""
    now = now or datetime.now()
    dest_root = os.path.abspath(dest_root or os.path.join(root, "dist"))
    name = f"{PACKAGE_NAME}_{now:%Y%m%d_%H%M%S}"
    final = os.path.join(dest_root, name)
    inside, dist = (os.path.normcase(os.path.abspath(p)) for p in (root, os.path.join(root, "dist")))
    target = os.path.normcase(dest_root)
    if (target == inside or target.startswith(inside + os.sep)) and \
            not (target == dist or target.startswith(dist + os.sep)):
        raise PackageError("put the package in dist\\ or outside the tool's folder - not among its files")
    if os.path.exists(final):
        raise PackageError(f"{final} already exists")
    if with_data and sync:
        import gmes_twin
        report = gmes_twin.sync_quietly()
        if report is not None and report.conflicts:
            for kind, item, words in report.conflicts:
                log(f"  note: not synced with GMES Automation - {kind} {item}: {words} "
                    "(the command line's version is packaged)")
    items = plan(root, with_data)
    partial = final + ".partial"
    os.makedirs(partial)
    try:
        files = {}
        for src, rel, kind in items:
            dst = os.path.join(partial, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            digest = sha256(dst)
            if digest != sha256(src):
                raise PackageError(f"{rel} changed while it was being copied - build again")
            files[rel.replace(os.sep, "/")] = {"size": os.path.getsize(dst), "sha256": digest, "kind": kind}
        schedules, schedule_problem = (snapshot() if snapshot else schedule_snapshot()) if with_data \
            else ([], "")
        if with_data:
            with open(os.path.join(partial, "schedules.json"), "w", encoding="utf-8") as fh:
                json.dump({"from_pc": os.environ.get("COMPUTERNAME", ""), "made": f"{now:%Y-%m-%d %H:%M:%S}",
                           "schedules": schedules}, fh, indent=2)
        with open(os.path.join(partial, "START_HERE.txt"), "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(START_HERE.format(built=f"{now:%Y-%m-%d %H:%M}"))
        warnings = []
        if schedule_problem:
            warnings.append(schedule_problem)
        for folder, users in personal_folders(root, with_data):
            if folder.get("personal"):
                warnings.append(f"{', '.join(users)} save(s) to {folder['path']} - a folder of ONE "
                                "Windows user on THIS PC; on the server run:  "
                                f'GMES_Workflow.bat move-folder "{folder["path"]}" "<a folder there>"')
        counts = {k: sum(1 for f in files.values() if f["kind"] == k) for k in ("tool", "guide", "data")}
        manifest = {"package": name, "built": f"{now:%Y-%m-%d %H:%M:%S}",
                    "built_on": os.environ.get("COMPUTERNAME", ""), "built_by": os.environ.get("USERNAME", ""),
                    "source": root, "commit": git_commit(root), "python": sys.version.split()[0],
                    "with_data": with_data, "counts": counts,
                    "recordings": sum(1 for r in files if re.fullmatch(r"screens/[^/]+\.json", r)
                                      and not r.endswith(("confirmations.json", "rowexport.json"))),
                    "batches": sum(1 for r in files if r.startswith("screens/batches/")),
                    "schedules": len(schedules), "warnings": warnings, "files": files}
        with open(os.path.join(partial, "MANIFEST.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1, sort_keys=False)
        os.replace(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)          # only what THIS build made
        raise
    zip_path = None
    if make_zip:
        zip_path = final + ".zip"
        tmp = zip_path + ".partial"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for dirpath, _dirs, names in os.walk(final):
                for n in sorted(names):
                    full = os.path.join(dirpath, n)
                    zf.write(full, os.path.join(name, os.path.relpath(full, final)))
        with zipfile.ZipFile(tmp) as zf:
            bad = zf.testzip()
            if bad:
                raise PackageError(f"the zip is damaged at {bad} - build again")
        os.replace(tmp, zip_path)
    return final, zip_path, manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--to", help="where to put it (default: dist\\ beside the tool)")
    p.add_argument("--no-data", action="store_true", help="the tool only: no recordings, batches, checks")
    p.add_argument("--no-zip", action="store_true", help="the folder only")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].lower() == "package":            # GMES_Workflow.bat package ...
        argv = argv[1:]
    a = p.parse_args(argv)
    try:
        folder, zip_path, m = build(a.to, with_data=not a.no_data, make_zip=not a.no_zip)
    except (PackageError, OSError) as e:
        print(f"ERROR: {e}")
        return 1
    c = m["counts"]
    print(f"\nPackage ready: {folder}")
    if zip_path:
        print(f"         zip : {zip_path}  ({os.path.getsize(zip_path) / 1e6:.1f} MB)")
    print(f"     content : {c['tool']} tool files, {c['guide']} guides"
          + (f", {m['recordings']} recordings, {m['batches']} batches, {m['schedules']} schedules"
             if m["with_data"] else " (no data)"))
    for w in m["warnings"]:
        print(f"     WARNING : {w}")
    print("\nOn the server: unzip it to a short local folder (e.g. C:\\gmes), then read START_HERE.txt.")
    if m["schedules"]:
        print(f"Once the server runs the {m['schedules']} schedule(s), remove them HERE - otherwise both PCs "
              "export the same batches every night:  python gmes_batch.py schedules  /  "
              "python gmes_batch.py unschedule <batch>  (GMES Automation: its Schedules page)")
    if m["with_data"]:
        print("It holds production data (filters, folders) - move it like a work file; never put it in git.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
