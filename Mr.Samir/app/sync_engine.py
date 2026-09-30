"""Copy the G-MES engine modules this app needs into app/engine, byte for byte.

The engine has ONE source of truth: the flat modules at the repository root
(CLAUDE.md section 0). This app never edits them and never re-implements them;
it carries identical copies so the folder can be handed to another PC on its own.
`python sync_engine.py --check` fails when a copy differs from its original
(tests/test_samir.py runs it), so the copies cannot drift into a second engine.
"""
import hashlib
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # the repository root
ENGINE = os.path.join(HERE, "engine")
SEEDS = ("gmes_core", "gmes_login", "gmes_common", "gmes_data", "gmes_credentials",
         "cdp_common", "gmes_open_screen", "gmes_profile", "gmes_log", "gmes_redact",
         "gmes_browsers")
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


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def check():
    """Problems, as a list of strings; empty when every copy is identical."""
    problems = []
    for name in closure():
        src, dst = os.path.join(ROOT, name + ".py"), os.path.join(ENGINE, name + ".py")
        if not os.path.isfile(dst):
            problems.append(f"missing copy: {name}.py")
        elif digest(src) != digest(dst):
            problems.append(f"differs from the root original: {name}.py")
    if os.path.isdir(ENGINE):
        wanted = {n + ".py" for n in closure()}
        for n in os.listdir(ENGINE):
            if n.endswith(".py") and n not in wanted:
                problems.append(f"not part of the engine closure: {n}")
    return problems


def sync():
    os.makedirs(ENGINE, exist_ok=True)
    names = closure()
    for name in names:
        shutil.copyfile(os.path.join(ROOT, name + ".py"), os.path.join(ENGINE, name + ".py"))
    return names


if __name__ == "__main__":
    if "--check" in sys.argv:
        found = check()
        for p in found:
            print("PROBLEM:", p)
        print("engine copies identical" if not found else f"{len(found)} problem(s)")
        sys.exit(1 if found else 0)
    done = sync()
    print(f"copied {len(done)} modules into {ENGINE}:")
    print("  " + ", ".join(done))
