"""How the tool notices a screen has changed since it was last learned.

Forked from gmes_profile.py's `fingerprint()`/`describe_change()` (NOT its
`field_ref`/`grid_ref`/`tree_ref`/`load`/`save`/`known`/`forget` - those
build and persist the on-disk profile itself and belong to `profiles/`, a
later phase of this migration). `info` here is a live `gmes.contracts.
ScreenInfo` (discovery/screen_discovery.py's `discover()`); `profile` and
the `ref` dicts inside it stay plain dicts, matching the JSON shape
`profiles/store.py` will read off disk once it exists - there is no reason
to invent a typed shape for one side of a comparison and not the other
before the thing that actually produces it is built.
"""
import hashlib


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
    parts = {f"f:{f.dataset}.{f.column}" for f in info.filters}
    parts |= {f"g:{g.dataset}" for g in info.grids}
    return hashlib.sha1("|".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def _still_there(info, ref):
    """Is the control this profile refers to still on the screen?"""
    if not ref:
        return True
    for f in tuple(info.filters) + tuple(info.unbound):
        if ref.get("column") and f.column == ref["column"] \
                and f.dataset == ref["dataset"]:
            return True
        if not ref.get("column") and f.control == ref.get("control"):
            return True
    return False


def missing_references(profile, info):
    """Controls this profile names that are not on the screen any more.

    Checked where the references are actually USED - after any saved
    left-panel options have been applied - because an option rebuilds the
    panel, and a date field that belongs to the rebuilt panel is legitimately
    absent from the screen as it first opens."""
    problems = []
    for name in ("from", "to"):
        ref = profile.get(name)
        if ref and not _still_there(info, ref):
            problems.append(f"the '{name}' date field {ref['column']!r} is gone")

    grid = profile.get("grid")
    if grid and grid.get("dataset"):
        if not any(g.dataset == grid["dataset"] for g in info.grids):
            problems.append(f"the result grid {grid['dataset']!r} is gone")
    return problems


def shape_changed(profile, info):
    """Whether this is still the screen that was learned.

    Compared against the screen AS IT OPENS, and recorded at that same
    moment, because the two have to be the same moment to be comparable.
    They were not: the shape was recorded at the end of a run, by which time
    any left-panel option had rebuilt the panel, while the check ran on the
    freshly opened screen. A screen recorded with an option therefore never
    matched itself, and the tool refused to replay anything it had just
    learned - on exactly the screens where options matter most (Plan Date
    versus Create Date, Org versus Prod). See HISTORY.md Phase 48."""
    return bool(profile.get("fingerprint")) and profile["fingerprint"] != fingerprint(info)


def describe_change(profile, info):
    """What, if anything, has moved since this profile was proven.

    Returns a list of plain-English problems. An empty list means the profile
    can be replayed. A non-empty one means it must NOT be: the run falls back
    to discovering the screen again and says why, rather than quietly
    re-matching and possibly picking a different field.

    Both halves at once, for a caller holding a single screen state. A run
    checks them at the two different moments they belong to; see
    `shape_changed` and `missing_references`."""
    problems = missing_references(profile, info)
    if not problems and shape_changed(profile, info):
        problems.append("the screen's controls have changed since this was learned "
                        "(nothing the profile uses has moved, but it is no longer "
                        "the same screen)")
    return problems
