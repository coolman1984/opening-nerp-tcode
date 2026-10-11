"""Edit a recording without opening G-MES - every part a person decides, and nothing it observed.

A recording holds two kinds of things. What the screen TOLD the tool (its fingerprint, the bound
fields, the grid's dataset) is evidence, re-learned by the next run; it is never edited here.
What a PERSON decided - the division, the period, each filter, the options, the popup picks, the
date to prove, the file kind, where the file goes - is a choice, and this module changes it:

    division      'VD', 'Production 1 | Production 2' (one query per part), 'A; B' (ticked together)
    from / to     the remembered period (YYYYMMDD or YYYYMM; '' clears)
    verify        the result column that proves the date ('planYmd', 'col=value'; '' clears)
    sets / unset  filters by label, column or control name: {'paramTecoYn': 'All'} / ['old one']
    options_add / options_remove   left-panel choices ('Weekly', 'Shift')
    picks_add / picks_remove       popup-list choices ('PO Type=Normal P/O') / labels
    export        'xlsx', 'csv', 'none', or 'default' (the tool's own default)
    output_dir    the pinned folder ('' = no pin)
    distribute_to every extra folder a file is copied to (the whole list)
    period_column the CSV starts with Period From / Period To / Division (True/False)
    period_check  'screen' (the screen defines its own period) or '' (prove it in the rows)

Every edit: the change is checked first (a refusal says why), the recording as it was is kept in
the screen's library folder (versions/), the new one is written in one step, and the history says
what changed. An edited recording has not been PROVEN - its card says so until a record check
(the bare replay, judged) has passed again. HISTORY.md Phase 131."""
import json
import os
import re

import gmes_dossier
import gmes_profile

EXPORTS = ("xlsx", "csv", "none", "default")
KEYS = ("division", "from", "to", "verify", "sets", "unset", "options_add", "options_remove",
        "picks_add", "picks_remove", "export", "output_dir", "distribute_to", "period_column",
        "period_check")


class Refused(ValueError):
    """The edit cannot be made; the message says why."""


def _code(code):
    try:
        return gmes_dossier._code(code)
    except ValueError as e:
        raise Refused(str(e)) from e


def _date(value, what):
    value = re.sub(r"\D", "", str(value or ""))
    if not value:
        return ""
    import gmes_core as core
    if len(value) == 6:                                   # a month
        if not (1 <= int(value[4:]) <= 12):
            raise Refused(f"{what}: {value} is not a month (YYYYMM)")
        return value
    try:
        return core.normalise_date(value)
    except ValueError as e:
        raise Refused(f"{what}: {e}") from e


def _folder(value, what):
    value = str(value or "").strip().strip('"')
    if not value:
        return ""
    if re.search(r'[<>"|?*]', value.replace(":\\", "")[2:] if re.match(r"^[A-Za-z]:\\", value) else value):
        raise Refused(f"{what}: {value!r} is not a folder name")
    if not (value.startswith("\\\\") or re.match(r"^[A-Za-z]:\\", value)):
        raise Refused(f"{what}: give a full folder - D:\\... or \\\\server\\share\\... - not {value!r}")
    return value


def _pick(item):
    import gmes_core as core
    if isinstance(item, dict):
        label, value = str(item.get("label") or "").strip(), str(item.get("value") or "").strip()
        if not label or not value:
            raise Refused("a pick needs a label and a value")
        return {"label": label, "value": value}
    try:
        return core.parse_pick(item)
    except ValueError as e:
        raise Refused(str(e)) from e


def _option_names(o):
    import gmes_core as core
    if isinstance(o, dict):
        return {str(o.get(k) or "").strip().lower() for k in ("key", "name", "label") if o.get(k)}
    text = str(o).strip()
    return {text.lower(), core.option_key(text).lower()}


def plan(profile, change):
    """(new profile, [change lines], [warnings]) - nothing is written. Raises Refused."""
    import gmes_core as core
    if not isinstance(profile, dict) or not profile.get("learned"):
        raise Refused("only a screen recorded on this PC can be edited - record it first")
    unknown = sorted(set(change or {}) - set(KEYS))
    if unknown:
        raise Refused(f"unknown part(s) of a recording: {', '.join(unknown)}")
    new = json.loads(json.dumps(profile))
    values = gmes_profile.last_values(new)
    values.setdefault("sets", {})
    lines, warnings = [], []

    def note(name, before, after):
        if before != after:
            lines.append(f"{name}: {before if before not in ('', None, [], {}) else '(none)'} -> "
                         f"{after if after not in ('', None, [], {}) else '(none)'}")

    if "division" in change:
        division = re.sub(r"\s+", " ", str(change["division"] or "")).strip()
        for part in core.division_names(division) if division else []:
            if not part.strip():
                raise Refused("the division has an empty part")
        note("division", values.get("division") or "", division)
        values["division"] = division
    for end in ("from", "to"):
        if end in change:
            value = _date(change[end], f"the period's {end}")
            note(end, values.get(end) or "", value)
            values[end] = value
    if values.get("from") and values.get("to") and len(values["from"]) == len(values["to"]) \
            and values["to"] < values["from"]:
        raise Refused(f"the period ends ({values['to']}) before it starts ({values['from']})")
    if "verify" in change:
        verify = str(change["verify"] or "").strip()
        if verify and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(=.+)?", verify):
            raise Refused(f"verify wants a result column name (optionally =value), not {verify!r}")
        note("date proven in", values.get("verify") or "", verify)
        values["verify"] = verify
    sets = dict(values.get("sets") or {})
    for key in change.get("unset") or []:
        hit = next((k for k in sets if k.strip().lower() == str(key).strip().lower()), None)
        if hit is None:
            raise Refused(f"there is no filter {key!r} in this recording")
        note(f"filter {hit}", sets[hit], "")
        sets.pop(hit)
    for key, value in (change.get("sets") or {}).items():
        key = str(key).strip()
        if not key:
            raise Refused("a filter needs a name")
        hit = next((k for k in sets if k.strip().lower() == key.lower()), key)
        value = str(value if value is not None else "").strip()
        note(f"filter {hit}", sets.get(hit, ""), value)
        sets[hit] = value
    if sets != (values.get("sets") or {}):
        values["sets"] = sets
        desc = gmes_dossier.describe(profile.get("screen") or "") if profile.get("screen") else None
        if desc:
            known = {str(f.get(k) or "").strip().lower() for f in (desc.get("filters") or []) +
                     (desc.get("unbound") or []) for k in ("label", "column", "control")}
            for key in sets:
                if key.strip().lower() not in known:
                    warnings.append(f"filter {key!r} is not among the screen's filters in its newest describe "
                                    "- the next run refuses it if the screen really has no such field")
    options = list(new.get("options") or [])
    for name in change.get("options_remove") or []:
        want = str(name).strip().lower()
        keep = [o for o in options if want not in _option_names(o)]
        if len(keep) == len(options):
            raise Refused(f"there is no option {name!r} in this recording")
        options = keep
        note("option", name, "")
    for name in change.get("options_add") or []:
        name = str(name).strip()
        if not name:
            raise Refused("an option needs a name")
        if any(name.lower() in _option_names(o) for o in options):
            continue
        # A label, the shape the next run turns into the control's own stable identity
        # (gmes_core.resolve_option) - the same as a typed --option.
        options.append(name)
        note("option", "", name)
    if options != list(new.get("options") or []):
        new["options"] = options
    recipe = dict(new.get("recipe") or {})
    picks = list(recipe.get("picks") or [])
    for label in change.get("picks_remove") or []:
        keep = [p for p in picks if str(p.get("label") or "").strip().lower() != str(label).strip().lower()]
        if len(keep) == len(picks):
            raise Refused(f"there is no pick {label!r} in this recording")
        note(f"pick {label}", next(p.get("value") for p in picks if p not in keep), "")
        picks = keep
    for item in change.get("picks_add") or []:
        pick = _pick(item)
        old = next((p for p in picks if p.get("label", "").lower() == pick["label"].lower()), None)
        note(f"pick {pick['label']}", (old or {}).get("value", ""), pick["value"])
        picks = [p for p in picks if p is not old] + [pick]
    if picks != list(recipe.get("picks") or []):
        if picks:
            recipe["picks"] = picks
        else:
            recipe.pop("picks", None)
    if "period_column" in change:
        on = bool(change["period_column"])
        note("CSV period columns", "yes" if recipe.get("period_column") else "no", "yes" if on else "no")
        if on:
            recipe["period_column"] = True
        else:
            recipe.pop("period_column", None)
    if recipe != (new.get("recipe") or {}):
        if recipe:
            new["recipe"] = recipe
        else:
            new.pop("recipe", None)
    if "period_check" in change:
        pc = str(change["period_check"] or "").strip().lower()
        if pc not in ("", "screen"):
            raise Refused("period_check is 'screen' or empty")
        note("period check", values.get("period_check") or "", pc)
        if pc:
            values["period_check"] = pc
        else:
            values.pop("period_check", None)
    if "export" in change:
        export = str(change["export"] or "default").strip().lower()
        export = "xlsx" if export == "both" else export          # 'both' means Excel since Phase 98.1
        if export not in EXPORTS:
            raise Refused(f"export is one of {', '.join(EXPORTS)}, not {export!r}")
        before = new.get("export") or "default"
        note("files", before, export)
        if export == "default":
            new.pop("export", None)
        else:
            new["export"] = export
    if "output_dir" in change:
        folder = _folder(change["output_dir"], "the save folder")
        note("saved in", new.get("output_dir") or "", folder)
        if folder:
            new["output_dir"] = folder
        else:
            new.pop("output_dir", None)
    if "distribute_to" in change:
        targets = []
        for item in change["distribute_to"] or []:
            folder = _folder(item, "a delivery folder")
            if folder and folder.lower() not in {t.lower() for t in targets}:
                targets.append(folder)
        note("also copied to", "; ".join(new.get("distribute_to") or []), "; ".join(targets))
        if targets:
            new["distribute_to"] = targets
        else:
            new.pop("distribute_to", None)
    if (new.get("recipe") or {}).get("period_column") and (new.get("export") or "") != "csv":
        warnings.append("CSV period columns only matter when the files are CSV")
    new["values"] = values
    return new, lines, warnings


def apply(code, change, by="", dry_run=False, now=None):
    """Make the edit. Returns {"code", "changes", "warnings", "version", "saved"}; with dry_run
    nothing is written (a preview). Raises Refused."""
    code = _code(code)
    profile = gmes_profile.load(code)
    if not profile:
        raise Refused(f"{code} is not known on this PC")
    local = gmes_profile._read(gmes_profile.path_for(code))
    if not local:
        raise Refused(f"{code} is not recorded on this PC - record it first")
    new, lines, warnings = plan(local, change or {})
    out = {"code": code, "changes": lines, "warnings": warnings, "version": None, "saved": False}
    if dry_run or not lines:
        return out
    version = gmes_dossier.snapshot_version(code, "before-edit", now=now)
    gmes_profile._write_atomic(gmes_profile.path_for(code), new)
    out.update(version=os.path.basename(version) if version else None, saved=True)
    gmes_dossier.event(code, "edit", now=now, by=by or None, changes=lines,
                       version=out["version"], warnings=warnings or None)
    gmes_dossier.write_index()
    return out


def restore(code, name, by="", now=None):
    """Put an earlier version back (the current one is kept as a version first)."""
    code = _code(code)
    try:
        old = gmes_dossier.version_data(code, name)
    except ValueError as e:
        raise Refused(str(e)) from e
    if str(old.get("screen") or "").upper() not in ("", code):
        raise Refused(f"{name} is the recording of {old.get('screen')}, not {code}")
    current = gmes_profile._read(gmes_profile.path_for(code)) or {}
    lines = diff(current, old)
    if not lines:
        return {"code": code, "changes": [], "version": None, "saved": False}
    version = gmes_dossier.snapshot_version(code, "before-restore", now=now)
    gmes_profile._write_atomic(gmes_profile.path_for(code), old)
    gmes_dossier.event(code, "restore", now=now, by=by or None, changes=lines, restored=name,
                       version=os.path.basename(version) if version else None)
    gmes_dossier.write_index()
    return {"code": code, "changes": lines, "version": os.path.basename(version) if version else None,
            "saved": True}


def diff(a, b):
    """What a person would see change between two recordings - the decided parts, in words."""
    la = dict(gmes_dossier.recipe_lines(a or {}))
    lb = dict(gmes_dossier.recipe_lines(b or {}))
    out = []
    for key in list(dict.fromkeys(list(la) + list(lb))):
        if la.get(key) != lb.get(key):
            out.append(f"{key}: {la.get(key, '(none)')} -> {lb.get(key, '(none)')}")
    if not out and (a or {}).get("learned") != (b or {}).get("learned"):
        out.append(f"recorded: {(a or {}).get('learned')} -> {(b or {}).get('learned')}")
    return out


def change_from_args(sets=(), unset=(), division=None, date_from=None, date_to=None, verify=None,
                     options_add=(), options_remove=(), picks_add=(), picks_remove=(), export=None,
                     output_dir=None, clear_output_dir=False, distribute_to=None, no_distribute=False,
                     period_column=None, period_check=None):
    """A change dict from command-line pieces (gmes_report.py edit)."""
    change = {}
    if division is not None:
        change["division"] = division
    if date_from is not None:
        change["from"] = date_from
    if date_to is not None:
        change["to"] = date_to
    if verify is not None:
        change["verify"] = verify
    if sets:
        change["sets"] = {}
        for item in sets:
            key, sep, value = str(item).partition("=")
            if not sep or not key.strip():
                raise Refused(f"--set wants NAME=VALUE, not {item!r}")
            change["sets"][key.strip()] = value.strip()
    if unset:
        change["unset"] = list(unset)
    if options_add:
        change["options_add"] = list(options_add)
    if options_remove:
        change["options_remove"] = list(options_remove)
    if picks_add:
        change["picks_add"] = list(picks_add)
    if picks_remove:
        change["picks_remove"] = list(picks_remove)
    if export is not None:
        change["export"] = export
    if clear_output_dir:
        change["output_dir"] = ""
    elif output_dir is not None:
        change["output_dir"] = output_dir
    if no_distribute:
        change["distribute_to"] = []
    elif distribute_to is not None:
        change["distribute_to"] = list(distribute_to)
    if period_column is not None:
        change["period_column"] = period_column
    if period_check is not None:
        change["period_check"] = period_check
    return change
