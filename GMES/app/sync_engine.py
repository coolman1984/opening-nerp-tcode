"""Copy what GMES Automation needs from the project into app/, byte for byte.

    app/engine/   the flat engine modules (CLAUDE.md section 0: ONE engine)
    app/shipped/  the committed screen structures (screens_known/)

The app never edits them and never re-implements them; it carries identical
copies so the GMES folder can be handed to another PC on its own.
`python sync_engine.py --check` fails when a copy differs from its original
(tests/test_gmes_app.py runs it), so the copies cannot drift into a second engine.
"""
import hashlib
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # the repository root
ENGINE = os.path.join(HERE, "engine")
SHIPPED = os.path.join(HERE, "shipped")
SHIPPED_SOURCE = os.path.join(ROOT, "screens_known")
SEEDS = ("gmes_core", "gmes_login", "gmes_common", "gmes_data", "gmes_credentials",
         "cdp_common", "gmes_open_screen", "gmes_profile", "gmes_log", "gmes_redact",
         "gmes_browsers", "gmes_batch", "gmes_schedule", "gmes_library")
IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)


def root_modules():
    return {n[:-3] for n in os.listdir(ROOT) if n.endswith(".py")}


def closure():
    """Every root module reachable by an import line from the seeds."""
    known, todo, seen = root_modules(), list(SEEDS), set()
    while todo:
        name = todo.pop()
        if name in seen or name not in known:
            continue
        seen.add(name)
        with open(os.path.join(ROOT, name + ".py"), encoding="utf-8") as fh:
            todo.extend(IMPORT_RE.findall(fh.read()))
    return sorted(seen)


def shipped_files():
    try:
        return sorted(n for n in os.listdir(SHIPPED_SOURCE) if n.endswith(".json"))
    except OSError:
        return []


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _compare(names, src_dir, dst_dir, suffix, what):
    problems = []
    for name in names:
        src, dst = os.path.join(src_dir, name + suffix), os.path.join(dst_dir, name + suffix)
        if not os.path.isfile(dst):
            problems.append(f"missing {what}: {name}{suffix}")
        elif digest(src) != digest(dst):
            problems.append(f"{what} differs from the project's original: {name}{suffix}")
    if os.path.isdir(dst_dir):
        wanted = {n + suffix for n in names}
        for n in os.listdir(dst_dir):
            if n.endswith(suffix) and n not in wanted:
                problems.append(f"{what} that is not in the project: {n}")
    return problems


def check():
    """Problems, as a list of strings; empty when every copy is identical."""
    return (_compare(closure(), ROOT, ENGINE, ".py", "engine copy")
            + _compare([n[:-5] for n in shipped_files()], SHIPPED_SOURCE, SHIPPED, ".json",
                       "shipped screen"))


def sync():
    os.makedirs(ENGINE, exist_ok=True)
    os.makedirs(SHIPPED, exist_ok=True)
    names = closure()
    for name in names:
        shutil.copyfile(os.path.join(ROOT, name + ".py"), os.path.join(ENGINE, name + ".py"))
    for stale in os.listdir(ENGINE):
        if stale.endswith(".py") and stale[:-3] not in names:
            os.remove(os.path.join(ENGINE, stale))
    shipped = shipped_files()
    for name in shipped:
        shutil.copyfile(os.path.join(SHIPPED_SOURCE, name), os.path.join(SHIPPED, name))
    for stale in os.listdir(SHIPPED):
        if stale.endswith(".json") and stale not in shipped:
            os.remove(os.path.join(SHIPPED, stale))
    return names, shipped


if __name__ == "__main__":
    if "--check" in sys.argv:
        found = check()
        for p in found:
            print("PROBLEM:", p)
        print("engine and shipped copies identical" if not found else f"{len(found)} problem(s)")
        sys.exit(1 if found else 0)
    done, shipped = sync()
    print(f"copied {len(done)} engine modules and {len(shipped)} shipped screens:")
    print("  " + ", ".join(done))
