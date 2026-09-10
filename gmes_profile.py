"""
What the tool remembers about a G-MES screen after a run that actually
worked - step 9 of the basic workflow, and nothing more.

A profile is NOT a recording. It holds no coordinates, no window ids, no
dataset contents. It holds three kinds of thing:

  * which control this screen means by "from", "to" and "division"
  * which grid holds the result
  * a fingerprint of the screen as it was when the run succeeded

Everything else is rediscovered on every run, because it is cheap and always
true. The profile only answers the questions discovery cannot: on a screen
with three date fields, which one did the run that worked actually use?

Why so little is saved
----------------------
G-MES renumbers a screen's ids on every open (winPPM0219_0_516 ->
winPPM0219_0_315), so anything positional is stale before it is even reused.
And the worst bug in this project's history came from reusing a remembered
dataset name: a run reported 875 rows - the previous screen's count - when
the screen had returned 17. So what is saved here is deliberately limited to
names that are stable by construction, and every one of them is checked
against the live screen before it is trusted.

Fields are copied out by name, one at a time. That is an allowlist, and it
is deliberate: a G-MES form tree contains live session tokens (an ordinary
looking `dsAnyframeDVO` carries `tokenId` and `refreshTokenId`), so anything
that serialised "whatever was discovered" would write credentials to disk.
"""
import hashlib
import json
import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENS_DIR = os.path.join(SCRIPT_DIR, "screens")


def path_for(code):
    return os.path.join(SCREENS_DIR, f"{code.strip().upper()}.json")


# ---------------------------------------------------------------------------
# References - the only shapes ever written to disk
# ---------------------------------------------------------------------------

def field_ref(flt):
    """A filter, by the names that survive a reopen. No value, no id."""
    if not flt:
        return None
    return {"dataset": flt.get("dataset", ""), "column": flt.get("column", ""),
            "control": flt.get("control", ""), "form": flt.get("form", ""),
            "label": flt.get("label", "")}


def grid_ref(grid):
    if not grid:
        return None
    return {"name": grid.get("name", ""), "dataset": grid.get("dataset", ""),
            "form": grid.get("form", "")}


def tree_ref(form, dataset, entry):
    return {"form": form or "", "dataset": dataset or "", "entry": entry or ""}


# ---------------------------------------------------------------------------
# Fingerprint - how we notice the screen changed
# ---------------------------------------------------------------------------

def fingerprint(info):
    """A digest of the parts of the screen a profile is allowed to refer to:
    the bound filters, by dataset and column, and the result grids.

    Two things are deliberately NOT in it, and the first version of this
    included both. Running the same screen twice, seconds apart, reported
    "the screen's controls have changed" and threw away what it had just
    learned - a memory that erases itself on every run is worse than none,
    because it also cries wolf.

      * **Unbound inputs** are collected only when VISIBLE, and visibility
        moves with scrolling, tabs and panels that finish rendering late. It
        is not a property of the screen at all.
      * **The control name** of a bound filter, because one column can be
        bound to several controls and the one recorded is whichever was
        visible. `_still_there()` matches on dataset and column, so the
        fingerprint watches exactly what the profile actually uses -
        no more, or it fires on changes that cannot matter.

    Counted as SETS, not lists: two grids bound to the same dataset are the
    same result set as far as anything here is concerned, and how many of
    them the screen happens to have built is not a change worth reporting."""
    parts = {f"f:{f.get('dataset')}.{f.get('column')}"
             for f in info.get("filters", [])}
    parts |= {f"g:{g.get('dataset')}" for g in info.get("grids", [])}
    return hashlib.sha1("|".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def _still_there(info, ref):
    """Is the control this profile refers to still on the screen?"""
    if not ref:
        return True
    for f in info.get("filters", []) + info.get("unbound", []):
        if ref.get("column") and f.get("column") == ref["column"] \
                and f.get("dataset") == ref["dataset"]:
            return True
        if not ref.get("column") and f.get("control") == ref.get("control"):
            return True
    return False


def describe_change(profile, info):
    """What, if anything, has moved since this profile was proven.

    Returns a list of plain-English problems. An empty list means the profile
    can be replayed. A non-empty one means it must NOT be: the run falls back
    to discovering the screen again and says why, rather than quietly
    re-matching and possibly picking a different field."""
    problems = []
    for name in ("from", "to"):
        ref = profile.get(name)
        if ref and not _still_there(info, ref):
            problems.append(f"the '{name}' date field {ref['column']!r} is gone")

    grid = profile.get("grid")
    if grid and grid.get("dataset"):
        if not any(g.get("dataset") == grid["dataset"] for g in info.get("grids", [])):
            problems.append(f"the result grid {grid['dataset']!r} is gone")

    if not problems and profile.get("fingerprint") != fingerprint(info):
        problems.append("the screen's controls have changed since this was learned "
                        "(nothing the profile uses has moved, but it is no longer "
                        "the same screen)")
    return problems


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load(code):
    try:
        with open(path_for(code), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def forget(code):
    try:
        os.remove(path_for(code))
        return True
    except OSError:
        return False


def save(code, title, menu_id, info, from_ref=None, to_ref=None,
         division=None, grid=None, rows=0, command=""):
    """Write what a successful run proved. Called only after the export."""
    os.makedirs(SCREENS_DIR, exist_ok=True)
    data = {
        "screen": code.strip().upper(),
        "title": title or "",
        "menuId": menu_id or "",
        "learned": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fingerprint": fingerprint(info),
        "from": from_ref,
        "to": to_ref,
        "division": division,
        "grid": grid_ref(grid),
        "proved": {"rows": rows, "command": command},
    }
    with open(path_for(code), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path_for(code)


def summary(profile):
    """One line for the log."""
    if not profile:
        return "none"
    bits = []
    for name in ("from", "to"):
        ref = profile.get(name)
        if ref:
            bits.append(f"{name}={ref['column'] or ref['control']}")
    if profile.get("grid", {}).get("dataset"):
        bits.append(f"grid={profile['grid']['dataset']}")
    return f"learned {profile.get('learned', '?')}  " + "  ".join(bits)
