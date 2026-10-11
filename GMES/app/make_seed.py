"""Build the `seed` folder a server copy of GMES Automation carries (make_package.bat server).

The window beside a project syncs with it (CLAUDE.md 0a). A GMES folder handed to a server
has no project beside it, so it would start knowing nothing: no recordings, no batches, no
record checks, no HQ site. The seed is what the project knows, in the command line's own
layout, and `app_env.twin_root()` makes the window sync with it on start - additively, by
the twin's rules (nothing deleted, a batch saved differently on both sides left alone).

Taken, for SEEG's G-MES and every other site (sites/<site>/):
    screens/*.json                 recordings
    screens/batches/*.json         saved batches
    screens/certificates/*.json    record checks
    screens/confirmations.json     typed-period confirmations
Never: logs, exports, screenshots, schedules, the twin's state and backups, credentials.

A recording's pinned destination on a LOCAL drive (D:\\WORK\\...) names a folder of this PC;
on the server it would make a bare replay fail. It is left out of the seed copy, and said.
A network share (\\\\server\\share\\...) is the same folder from every PC and is kept.

    python make_seed.py [SEED_FOLDER]      default: GMES\\seed (replaced)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GMES_DIR = os.path.dirname(HERE)
PROJECT = os.path.dirname(GMES_DIR)
sys.path.insert(0, os.path.join(HERE, "engine"))

import app_env    # noqa: E402
import gmes_site  # noqa: E402
import gmes_twin  # noqa: E402

TAKEN = ("recordings", "batches", "certificates")


def is_share(path):
    return isinstance(path, str) and path.replace("/", "\\").startswith("\\\\")


def portable_recording(data):
    """(recording for another PC, [what was left out]). Only pins on a local drive go."""
    dropped = []
    if "output_dir" in data and not is_share(data["output_dir"]):
        dropped.append(f"output_dir {data['output_dir']}")
        data = dict(data)
        data.pop("output_dir")
    if isinstance(data.get("distribute_to"), list):
        keep = [p for p in data["distribute_to"] if is_share(p)]
        dropped += [f"distribute_to {p}" for p in data["distribute_to"] if not is_share(p)]
        if len(keep) != len(data["distribute_to"]):
            data = dict(data, distribute_to=keep)
            if not keep:
                data.pop("distribute_to")
    return data, dropped


def build(project=PROJECT, seed=None, log=print, leave_out=()):
    """Write the seed; returns {site label: {kind: count}}. The old seed is replaced.
    leave_out: (site, kind, lower-case file name) not to carry - a batch the two front
    ends disagree on is someone's undecided intent, and the seed would pick one side."""
    seed = seed or os.path.join(GMES_DIR, app_env.SEED)
    if os.path.isdir(seed):
        shutil.rmtree(seed)
    summary = {}
    sites = [(gmes_site.DEFAULT, project)] + [(s, gmes_site.site_root(project, s))
                                              for s in gmes_site.known_sites(project)]
    for site, root in sites:
        target = gmes_site.site_root(seed, site)
        counts = {}
        for kind, cli_parts, _exe, pattern, _how in gmes_twin.KINDS:
            if kind not in TAKEN:
                continue
            files = gmes_twin._files(os.path.join(root, *cli_parts), pattern, digest=False)
            out = os.path.join(target, *cli_parts)
            os.makedirs(out, exist_ok=True)
            files = {k: v for k, v in files.items() if (site, kind, k) not in leave_out}
            for _low, (path, _sha) in sorted(files.items()):
                dst = os.path.join(out, os.path.basename(path))
                data = gmes_twin._json(path) if kind == "recordings" else None
                if data is not None:
                    data, dropped = portable_recording(data)
                    for d in dropped:
                        log(f"  {site}: {os.path.basename(path)[:-5]} - left out {d} (a folder of this PC)")
                    with open(dst, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=2, ensure_ascii=False)
                else:
                    shutil.copyfile(path, dst)
            counts[kind] = len(files)
        conf = os.path.join(root, *gmes_twin.CONFIRMATIONS[0])
        if os.path.isfile(conf):
            shutil.copyfile(conf, os.path.join(target, *gmes_twin.CONFIRMATIONS[0]))
            counts["confirmations"] = 1
        cat = os.path.join(root, "screens", "popups.json")      # the popups met (Phase 132)
        if os.path.isfile(cat):
            os.makedirs(os.path.join(target, "screens"), exist_ok=True)
            shutil.copyfile(cat, os.path.join(target, "screens", "popups.json"))
            counts["popups"] = 1
        counts["library"] = copy_library(os.path.join(root, "screens", "library"),
                                         os.path.join(target, "screens", "library"))
        summary[site] = counts
    return summary


def copy_library(src, dst):
    """Each screen's library folder (gmes_dossier, HISTORY.md Phase 131): notes, history, the newest
    describe, the versions, and the screenshots of recordings, record checks and describes - the
    screen's own record. The daily runs' pictures stay on this PC. Returns the number of screens."""
    try:
        names = sorted(os.listdir(src))
    except OSError:
        return 0
    n = 0
    for name in names:
        folder = os.path.join(src, name)
        if not os.path.isdir(folder):
            continue
        out = os.path.join(dst, name)
        os.makedirs(out, exist_ok=True)
        for single in ("notes.md", "history.jsonl", "describe.json", "README.md"):
            if os.path.isfile(os.path.join(folder, single)):
                shutil.copyfile(os.path.join(folder, single), os.path.join(out, single))
        for sub, keep in (("versions", lambda f: f.endswith(".json")),
                          ("screenshots", lambda f: f.split("_", 2)[-1].split("-")[0] in ("record", "check", "describe"))):
            try:
                files = os.listdir(os.path.join(folder, sub))
            except OSError:
                continue
            for f in files:
                if keep(f):
                    os.makedirs(os.path.join(out, sub), exist_ok=True)
                    shutil.copyfile(os.path.join(folder, sub, f), os.path.join(out, sub, f))
        n += 1
    return n


def conflicts(report):
    """{(site, kind, lower-case file name)} of every twin conflict in eport."""
    out = set()
    for kind, name, _words in report.conflicts:
        site = gmes_site.DEFAULT
        if name.endswith(")") and " (" in name:
            name, site = name[:-1].rsplit(" (", 1)
        out.add((site, kind, name.lower()))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not gmes_twin.is_project_root(PROJECT):
        print("ERROR: this GMES folder does not sit in the project - there is nothing to seed from")
        return 2
    report = gmes_twin.sync(cli_root=PROJECT, exe_data=os.path.join(GMES_DIR, "data"))
    for line in report.lines():
        print(line)
    leave_out = conflicts(report)
    for site, kind, name in sorted(leave_out):
        print(f"  NOT in the seed: {kind} {name} ({site}) - the window and the command line disagree; "
              "save it once more in the one that is right, then make the package again")
    seed = argv[0] if argv else None
    summary = build(seed=seed, leave_out=leave_out)
    for site, counts in summary.items():
        print(f"  seed {site}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
