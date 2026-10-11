"""The screen library: one folder per recorded UI number - everything known about it, in one place.

    screens/library/
        INDEX.md                          every screen: code, title, status, last run, notes - the catalogue
        P1112WM01 - Production Plan by Order(Line)/
            README.md                     the screen's card, written by the tool: what it is, how it runs,
                                          what was proven, the newest screenshots, the notes  (regenerated)
            notes.md                      what people and agents LEARNED about it - problems, fixes,
                                          connectors (who uses the file) - never overwritten by the tool
            history.jsonl                 one line per event: recorded, run, record check, edit, restore,
                                          describe, note - the screen's own log, oldest first
            describe.json                 the newest describe: every filter, input, grid, tree and option
                                          the screen offers (the "code" side), with its time
            screenshots/                  <yyyymmdd_hhmmss>_<stage>.png - what the screen looked like
                                          (scope = just before Inquiry, result = after it, failure, describe;
                                          'record-'/'check-' when taken by a recording or a record check)
            versions/                     <yyyymmdd_hhmmss>_<reason>.json - the recording as it was before
                                          every edit or restore; any of them can be put back

The library is the screens folder's own (each G-MES site has one: sites/hq/screens/library), so
the command line and GMES Automation each keep it beside their recordings, and gmes_twin keeps
the two level like the recordings themselves (HISTORY.md Phase 131).

Nothing here may stop a run: every writer is best-effort and says nothing when it fails.
Screenshots and filter values can hold production data - the whole folder is runtime data,
git-ignored like screens/ (CLAUDE.md 2.4)."""
import datetime as _dt
import json
import os
import re
import shutil
import tempfile

import gmes_profile

LIBRARY = "library"
SHOTS = "screenshots"
VERSIONS = "versions"
HISTORY = "history.jsonl"
NOTES = "notes.md"
README = "README.md"
DESCRIBE = "describe.json"
INDEX = "INDEX.md"
# How many screenshots of ONE ordinary stage (scope, result, failure) are kept per screen: a
# daily batch adds two a day. Those of a recording, a record check or a describe are the
# screen's record and are kept far longer.
KEEP_RUN_SHOTS = 6
KEEP_RECORD_SHOTS = 40
STAGE_RE = re.compile(r"^(\d{8}_\d{6})_([a-z0-9-]+)\.png$")
VERSION_RE = re.compile(r"^(\d{8}_\d{6})_([a-z0-9-]+)\.json$")
# What a running recording or record check is doing - its screenshots carry the prefix
# ('record-scope', 'check-result'), and its history events say so. Set by gmes_recordcheck.
CONTEXT = {"stage": ""}
NOTES_HEAD = ("# Notes\n\nWhat was learned about this screen: problems and their fixes, what the "
              "file is used for and by whom, anything the next person or agent should know. "
              "The tool never overwrites this file.\n")


def enabled():
    """GMES_DOSSIER=off: the library writes nothing. Every offline test suite sets it (like
    GMES_TWIN=off): a test that runs a mocked screen must never log into the real library."""
    return os.environ.get("GMES_DOSSIER", "").strip().lower() not in ("off", "0", "no")


def _now():
    return _dt.datetime.now()


def _stamp(now=None):
    return (now or _now()).strftime("%Y%m%d_%H%M%S")


def _code(code):
    code = re.sub(r"\s+", "", str(code or "")).upper()
    if not re.fullmatch(gmes_profile.CODE_PATTERN, code, re.I):
        raise ValueError(f"not a UI number: {code!r}")
    return code


def safe_title(title):
    """A title as a folder-name part: Windows' forbidden characters out, at most 60 long."""
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(title or ""))
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:60].rstrip(" .")


def library_root():
    return os.path.join(gmes_profile.SCREENS_DIR, LIBRARY)


def _find(code):
    root = library_root()
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in sorted(names):
        if (name.upper() == code or name.upper().startswith(code + " - ")) and \
                os.path.isdir(os.path.join(root, name)):
            return os.path.join(root, name)
    return None


# Opening a file costs ~7 ms on a corporate PC (its scanner checks every open): 739 opens made the
# catalogue of 39 screens take 5.5 s. So a folder found once is remembered, and a title is only
# read when a caller passes one (the card and ensure() do - that is where a rename happens).
_FOLDERS = {}


def folder_for(code, title=None, create=False):
    """The screen's folder - '<CODE> - <title>' - or None when it has none (and create is off).
    A changed title (passed by the caller) renames the folder; the code at the front never changes."""
    code = _code(code)
    key = (library_root(), code)
    found = _FOLDERS.get(key)
    if not found or not os.path.isdir(found):
        found = _find(code)
    if found and title is None:
        _FOLDERS[key] = found
        return found
    if title is None:
        title = (gmes_profile.load(code) or {}).get("title") or ""
    wanted = code + (f" - {safe_title(title)}" if safe_title(title) else "")
    if found and os.path.basename(found) != wanted and title:
        target = os.path.join(library_root(), wanted)
        if not os.path.exists(target):
            try:
                os.replace(found, target)
                found = target
            except OSError:
                pass
    if found or not create:
        if found:
            _FOLDERS[key] = found
        return found
    path = os.path.join(library_root(), wanted)
    os.makedirs(path, exist_ok=True)
    _FOLDERS[key] = path
    return path


_CACHE = {}


def _cached(name, folder, load):
    """`load()` once per change of `folder` (its file names and their times) - certificates and run
    reports are read once, not once per screen."""
    try:
        sig = tuple(sorted((n, os.path.getmtime(os.path.join(folder, n))) for n in os.listdir(folder)))
    except OSError:
        sig = ()
    hit = _CACHE.get(name)
    if hit and hit[0] == (folder, sig):
        return hit[1]
    value = load()
    _CACHE[name] = ((folder, sig), value)
    return value


def certificates():
    import gmes_recordcheck as rc
    return _cached("certs", rc.cert_dir(), rc.certificates) or {}


def run_reports():
    """[(path, site or None, started, results)] of every run report, newest first - read once."""
    import gmes_batch

    def load():
        out = []
        folder = gmes_batch.REPORT_DIR
        try:
            names = sorted((n for n in os.listdir(folder) if n.startswith("batch_") and n.endswith(".json")),
                           reverse=True)
        except OSError:
            return out
        for n in names:
            data = _read_json(os.path.join(folder, n))
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                continue
            meta = data.get("meta") or {}
            out.append((os.path.join(folder, n), meta.get("site"), meta.get("started") or "", data["results"]))
        return out
    return _cached("reports", gmes_batch.REPORT_DIR, load)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".gmes-dossier-", suffix=".partial", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# History: the screen's own log
# --------------------------------------------------------------------------
def event(code, kind, now=None, **detail):
    """Append one event to the screen's history. Never raises - a log must not stop a run."""
    if not enabled():
        return None
    try:
        folder = folder_for(code, create=True)
        entry = {"at": (now or _now()).strftime("%Y-%m-%d %H:%M:%S"), "kind": kind}
        if CONTEXT.get("stage") and "context" not in detail:
            entry["context"] = CONTEXT["stage"]
        entry.update({k: v for k, v in detail.items() if v is not None})
        with open(os.path.join(folder, HISTORY), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        write_readme(code)
        return entry
    except Exception:                                        # noqa: BLE001 - best effort
        return None


def history(code, limit=None):
    folder = folder_for(code)
    out = []
    if not folder:
        return out
    try:
        with open(os.path.join(folder, HISTORY), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except OSError:
        return out
    return out[-limit:] if limit else out


def last_event(code, kinds):
    for item in reversed(history(code)):
        if item.get("kind") in kinds:
            return item
    return None


# --------------------------------------------------------------------------
# Screenshots
# --------------------------------------------------------------------------
def _shot_stage(stage):
    stage = re.sub(r"[^a-z0-9-]", "-", str(stage or "shot").lower()).strip("-") or "shot"
    prefix = CONTEXT.get("stage") or ""
    return f"{prefix}-{stage}" if prefix and not stage.startswith(prefix + "-") else stage


def shot(code, stage, capture=None, now=None):
    """Save what the screen looks like now as screenshots/<time>_<stage>.png. Returns the path or
    None. Never raises. `capture(path)` is gmes_common.capture_screenshot (injectable for tests).
    GMES_SHOTS=off switches screenshots off (the record of the screen keeps working)."""
    if os.environ.get("GMES_SHOTS", "").strip().lower() in ("off", "0", "no") or not enabled():
        return None
    try:
        folder = folder_for(code, create=True)
        stage = _shot_stage(stage)
        target = os.path.join(folder, SHOTS)
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, f"{_stamp(now)}_{stage}.png")
        if capture is None:
            import gmes_common
            capture = gmes_common.capture_screenshot
        saved = capture(path)
        if not saved or not os.path.isfile(path):
            return None
        prune(code)
        return path
    except Exception:                                        # noqa: BLE001 - best effort
        return None


def keep_for(stage):
    return KEEP_RECORD_SHOTS if stage.split("-")[0] in ("record", "check", "describe") else KEEP_RUN_SHOTS


def prune(code):
    """Keep the newest KEEP_RUN_SHOTS of every ordinary stage and KEEP_RECORD_SHOTS of a
    recording's, a check's or a describe's. Older ones are removed - they are pictures of a
    screen at a moment, and the run reports keep what each run did."""
    folder = folder_for(code)
    if not folder:
        return 0
    by_stage = {}
    for item in screenshots(code):
        by_stage.setdefault(item["stage"], []).append(item)
    removed = 0
    for stage, items in by_stage.items():
        for item in items[keep_for(stage):]:                 # newest first
            try:
                os.remove(os.path.join(folder, SHOTS, item["name"]))
                removed += 1
            except OSError:
                pass
    return removed


def screenshots(code):
    """[{name, stage, at, size}] newest first."""
    folder = folder_for(code)
    out = []
    if not folder:
        return out
    try:
        names = os.listdir(os.path.join(folder, SHOTS))
    except OSError:
        return out
    for name in names:
        m = STAGE_RE.match(name)
        if not m:
            continue
        try:
            size = os.path.getsize(os.path.join(folder, SHOTS, name))
        except OSError:
            continue
        at = _dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        out.append({"name": name, "stage": m.group(2), "at": at, "size": size})
    out.sort(key=lambda i: i["name"], reverse=True)
    return out


def shot_path(code, name):
    """The file of one screenshot, or None - the name must be a screenshot name of this screen."""
    if not STAGE_RE.match(str(name or "")):
        return None
    folder = folder_for(code)
    path = os.path.join(folder, SHOTS, name) if folder else None
    return path if path and os.path.isfile(path) else None


# --------------------------------------------------------------------------
# Versions of the recording
# --------------------------------------------------------------------------
def snapshot_version(code, reason, now=None):
    """Copy the recording as it is NOW into versions/ before it is changed. Returns the path,
    or None when there is no recording file to keep."""
    code = _code(code)
    src = gmes_profile.path_for(code)
    if not os.path.isfile(src) or not enabled():
        return None
    folder = folder_for(code, create=True)
    os.makedirs(os.path.join(folder, VERSIONS), exist_ok=True)
    reason = re.sub(r"[^a-z0-9-]", "-", str(reason or "change").lower()).strip("-") or "change"
    stamp = _stamp(now)
    path = os.path.join(folder, VERSIONS, f"{stamp}_{reason}.json")
    n = 1
    while os.path.exists(path):                              # two changes in one second
        n += 1
        path = os.path.join(folder, VERSIONS, f"{stamp}_{reason}-{n}.json")
    shutil.copy2(src, path)
    return path


def versions(code, details=True):
    """[{name, at, reason, learned}] newest first. details=False does not open the files (each open
    costs; a count or a list of names does not need what is inside)."""
    folder = folder_for(code)
    out = []
    if not folder:
        return out
    try:
        names = os.listdir(os.path.join(folder, VERSIONS))
    except OSError:
        return out
    for name in names:
        m = VERSION_RE.match(name)
        if not m or m.group(2) == "describe":          # a describe kept beside the versions is not a recording
            continue
        data = (_read_json(os.path.join(folder, VERSIONS, name)) or {}) if details else {}
        at = _dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        out.append({"name": name, "at": at, "reason": m.group(2), "learned": data.get("learned", "")})
    out.sort(key=lambda i: i["name"], reverse=True)
    return out


def version_data(code, name):
    if not VERSION_RE.match(str(name or "")):
        raise ValueError(f"not a version name: {name!r}")
    folder = folder_for(code)
    data = _read_json(os.path.join(folder, VERSIONS, name)) if folder else None
    if not isinstance(data, dict):
        raise ValueError(f"{code} has no version {name}")
    return data


# --------------------------------------------------------------------------
# Notes - the experience
# --------------------------------------------------------------------------
def notes(code):
    folder = folder_for(code)
    if not folder:
        return ""
    try:
        with open(os.path.join(folder, NOTES), encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError:
        return ""


def save_notes(code, text, by=""):
    """Replace the notes with `text` (the person edited the whole page)."""
    folder = folder_for(code, create=True)
    text = str(text or "").replace("\r\n", "\n")
    _write_text(os.path.join(folder, NOTES), text if text.endswith("\n") or not text else text + "\n")
    event(code, "notes", by=by or None, detail="the notes were edited")
    return os.path.join(folder, NOTES)


def add_note(code, text, by="", now=None):
    """Append one dated note."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("an empty note")
    folder = folder_for(code, create=True)
    path = os.path.join(folder, NOTES)
    current = notes(code) or NOTES_HEAD
    stamp = (now or _now()).strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {stamp}" + (f" - {by}" if by else "") + "\n\n" + text.replace("\r\n", "\n") + "\n"
    _write_text(path, current.rstrip("\n") + "\n" + entry)
    event(code, "note", by=by or None, detail=text[:200])
    return path


# --------------------------------------------------------------------------
# Describe - the code side of the screen
# --------------------------------------------------------------------------
def describe_data(screen):
    """What an open screen offers, as data: grids, bound filters, typed inputs, trees, options,
    the date fields and the columns that could verify a date. Shared by both front ends -
    the window's describe page and `gmes_report.py describe` - and kept as describe.json."""
    import gmes_core as core
    info = screen.info
    chosen, rivals = core.choose_grid(info)
    grids = []
    for g in info.get("grids", []):
        ds = info.get("datasets", {}).get(g["dataset"], {})
        grids.append({"name": g["name"], "dataset": g["dataset"], "cols": ds.get("cols"),
                      "rows": ds.get("rows"), "visible": bool(g.get("visible")),
                      "suggested": bool(chosen and g["name"] == chosen["name"])})
    filters = []
    for f in info.get("filters", []):
        filters.append({"label": f.get("label") or "", "column": f.get("column") or "",
                        "control": f.get("control") or "", "value": f.get("value") or "",
                        "visible": bool(f.get("visible")), "date": bool(core.is_date_field(f))})
    unbound = [{"label": u.get("label") or "", "control": u.get("control") or "",
                "value": u.get("value") or ""} for u in info.get("unbound", [])]
    frm, to, singles = core.date_targets(info)
    date_fields = [f["column"] for f in (frm, to) if f] or [f["column"] for f in singles]
    trees, tree_error = [], ""
    try:
        for t in screen.trees():
            if t.get("settable"):
                trees.append({"form": t["form"], "dataset": t["dataset"], "rows": t.get("rows"),
                              "names": list(t.get("names", [])), "checked": t.get("checked")})
    except Exception as e:                                  # noqa: BLE001
        tree_error = str(e)
    options, option_error = [], ""
    try:
        for o in screen.options():
            options.append({"label": o.get("label") or "", "key": core.option_key(o.get("name")),
                            "state": o.get("state") or "", "enabled": o.get("enabled", True),
                            "kind": o.get("kind") or ""})
    except Exception as e:                                  # noqa: BLE001
        option_error = str(e)
    verify_candidates = []
    try:
        if chosen:
            # a business date (`deftCreYmd`) before a clock time (`deftCreDt`): a production day
            # runs 08:00 to 08:00 (Q2111WM00, HISTORY.md Phase 122.11)
            verify_candidates = sorted(screen.candidate_verify_columns(chosen),
                                       key=lambda c: 0 if re.search(r"(ymd|date|day)$", c.lower()) else 1)
    except Exception:                                       # noqa: BLE001
        pass
    month = any(f["date"] and re.fullmatch(r"\d{6}", re.sub(r"\D", "", f["value"])) for f in filters) or \
        any(o["key"] in ("month",) and "selected" in o["state"] for o in options)
    return {"code": screen.code, "title": screen.title, "menu_id": screen.menu_id,
            "window": screen.win_id, "has_inquiry": bool(info.get("hasInquiry")),
            "has_excel": bool(info.get("hasExcel")), "grids": grids, "rivals": bool(rivals),
            "filters": filters, "unbound": unbound, "date_fields": date_fields,
            "trees": trees, "tree_error": tree_error, "options": options,
            "option_error": option_error, "verify_candidates": verify_candidates,
            "looks_monthly": bool(month)}


# Values a describe reads off the screen that must not be kept: a filter can hold a session
# token (CLAUDE.md 2.3) - the same words gmes_redact withholds from logs.
_SECRET = re.compile(r"(?i)token|password|passwd|secret|jwt")


def save_describe(code, data, now=None):
    """Keep a describe result as describe.json (the previous one in versions/), and log it.
    Returns {"path", "changes"}: what the screen offers now that the recording does not
    expect, from gmes_profile.describe_change() when the screen info is given."""
    code = _code(code)
    if not enabled():
        return None
    folder = folder_for(code, title=data.get("title") or None, create=True)
    clean = json.loads(json.dumps(data, default=str))
    for group in ("filters", "unbound"):
        for item in clean.get(group) or []:
            if _SECRET.search(f"{item.get('label', '')} {item.get('control', '')} {item.get('column', '')}"):
                item["value"] = "(withheld)"
    clean["described_at"] = (now or _now()).strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(folder, DESCRIBE)
    if os.path.isfile(path):
        os.makedirs(os.path.join(folder, VERSIONS), exist_ok=True)
        old = _read_json(path) or {}
        stamp = re.sub(r"\D", "", str(old.get("described_at") or ""))[:14]
        if len(stamp) == 14:
            dest = os.path.join(folder, VERSIONS, f"{stamp[:8]}_{stamp[8:]}_describe.json")
            if not os.path.exists(dest):
                shutil.copy2(path, dest)
    _write_text(path, json.dumps(clean, indent=2, ensure_ascii=False))
    event(code, "describe", detail=f"{len(clean.get('filters') or [])} filters, "
                                   f"{len(clean.get('grids') or [])} grids, "
                                   f"{len(clean.get('options') or [])} options")
    return path


def describe(code):
    folder = folder_for(code)
    data = _read_json(os.path.join(folder, DESCRIBE)) if folder else None
    return data if isinstance(data, dict) else None


def describe_drift(profile, desc):
    """What the recording names that the newest describe no longer shows - offline, words only."""
    if not isinstance(profile, dict) or not isinstance(desc, dict):
        return []
    import gmes_core as core
    out = []
    names = set()
    for f in (desc.get("filters") or []) + (desc.get("unbound") or []):
        for k in ("label", "column", "control"):
            if f.get(k):
                names.add(str(f[k]).strip().lower())
    for key in sorted(((profile.get("values") or {}).get("sets") or {})):
        if str(key).strip().lower() not in names:
            out.append(f"filter {key!r} is not among the screen's filters any more")
    grid = (profile.get("grid") or {}).get("dataset")
    if grid and desc.get("grids") and grid not in {g.get("dataset") for g in desc["grids"]}:
        out.append(f"the recorded grid {grid} is not on the screen any more")
    have = {(o.get("key") or "").lower() for o in desc.get("options") or []} | \
        {(o.get("label") or "").lower() for o in desc.get("options") or []}
    for o in profile.get("options") or []:
        key = (o.get("key") if isinstance(o, dict) else core.option_key(o)) or ""
        label = o.get("label") if isinstance(o, dict) else str(o)
        if desc.get("options") and key.lower() not in have and str(label).lower() not in have:
            out.append(f"option {label!r} is not offered any more")
    return out


# --------------------------------------------------------------------------
# The card (README.md) and the catalogue (INDEX.md)
# --------------------------------------------------------------------------
def recipe_lines(profile):
    """How the recording runs, in plain words - one (name, value) per thing it does."""
    import gmes_core as core
    p = profile or {}
    v = gmes_profile.last_values(p)
    rec = p.get("recipe") or {}
    lines = []
    division = v.get("division") or ""
    if division:
        how = (" (one query per part)" if "|" in division else
               " (all ticked in one query)" if ";" in division else "")
        lines.append(("Division", division + how))
    if v.get("from") or v.get("to"):
        lines.append(("Period (as recorded)", f"{v.get('from') or '?'} .. {v.get('to') or v.get('from') or '?'}"))
    for key, value in sorted((v.get("sets") or {}).items()):
        lines.append((f"Filter {key}", str(value)))
    if v.get("verify"):
        lines.append(("Date proven in", v["verify"]))
    if v.get("period_check") == "screen":
        lines.append(("Period check", "the screen defines its own period (decided when recorded)"))
    for o in p.get("options") or []:
        label = o.get("label") if isinstance(o, dict) else str(o)
        key = o.get("key") if isinstance(o, dict) else ""
        lines.append(("Option", f"{label}" + (f" [{key}]" if key and key != str(label).lower() else "")))
    for pick in rec.get("picks") or []:
        lines.append(("Pick from a list", f"{pick.get('label')} = {pick.get('value')}"))
    for step in rec.get("after_inquiry") or []:
        row = "; ".join(f"{k}={val}" for k, val in (step.get("row") or {}).items())
        lines.append(("After Inquiry", f"click {step.get('grid')} row [{row}] column {step.get('column')}"))
    if rec.get("result_grid"):
        lines.append(("Report table", rec["result_grid"]))
    if rec.get("export_via"):
        lines.append(("Export by", f"{rec['export_via'].get('grid')}: {' > '.join(rec['export_via'].get('menu') or [])}"))
    if rec.get("period_column"):
        lines.append(("CSV first columns", "Period From / Period To / Division"))
    grid = p.get("grid") or {}
    if grid.get("dataset"):
        lines.append(("Result grid", f"{grid.get('name') or '?'} -> {grid['dataset']}"))
    lines.append(("Files", {"csv": "CSV (the grid as shown)", "none": "no file (check only)",
                            "both": "Excel"}.get(p.get("export") or "", "Excel")
                  if p.get("export") else f"{core.DEFAULT_EXPORT} (the default)"))
    lines.append(("Saved in", p.get("output_dir") or "the tool's output folder (a run can choose another)"))
    for d in p.get("distribute_to") or []:
        lines.append(("Also copied to", d))
    return lines


def status_lines(code, profile):
    lines = []
    cert = certificates().get(code) or {}
    if cert:
        lines.append(("Record check", f"{cert.get('verdict')} at {cert.get('checked_at')}"))
    edited = last_event(code, ("edit", "restore"))
    if edited and (not cert or str(edited.get("at")) > str(cert.get("checked_at") or "")):
        lines.append(("Changed since", f"{edited.get('at')} ({edited['kind']}) - prove it with a record check"))
    runs = [e for e in history(code) if e.get("kind") == "run"]
    if runs:
        last = runs[-1]
        lines.append(("Last run", f"{last.get('at')}: " + ("ok, " + f"{int(last.get('rows') or 0):,} rows"
                                                         if last.get("ok") else f"FAILED - {last.get('error', '')[:120]}")))
        ok = sum(1 for e in runs if e.get("ok"))
        lines.append(("Runs logged", f"{len(runs)} ({ok} ok, {len(runs) - ok} failed)"))
    if profile and (profile.get("proved") or {}).get("rows") is not None:
        lines.append(("Rows when recorded", f"{int(profile['proved'].get('rows') or 0):,}"))
    return lines


def write_readme(code):
    """Regenerate the screen's card. Never raises."""
    try:
        code = _code(code)
        profile = gmes_profile.load(code) or {}
        folder = folder_for(code, title=profile.get("title") or None, create=True)
        import gmes_site
        title = profile.get("title") or ""
        out = [f"# {code}" + (f" - {title}" if title else ""), "",
               f"G-MES: {gmes_site.label()}"
               f"  ·  menu {profile.get('menuId') or '-'}  ·  recorded {profile.get('learned') or 'not on this PC'}", "",
               "## How it runs", ""]
        out += [f"- **{k}:** {v}" for k, v in recipe_lines(profile)] or ["- (not recorded on this PC)"]
        status = status_lines(code, profile)
        if status:
            out += ["", "## Proof", ""] + [f"- **{k}:** {v}" for k, v in status]
        desc = describe(code)
        if desc:
            drift = describe_drift(profile, desc)
            out += ["", "## The screen (newest describe)", "",
                    f"- described {desc.get('described_at')}: {len(desc.get('filters') or [])} bound filters, "
                    f"{len(desc.get('unbound') or [])} typed inputs, {len(desc.get('grids') or [])} grids, "
                    f"{len(desc.get('options') or [])} options, date fields "
                    f"{', '.join(desc.get('date_fields') or []) or 'none'}"]
            out += [f"- ⚠ {d}" for d in drift]
        shots = screenshots(code)
        if shots:
            out += ["", "## Screenshots (newest of each stage)", ""]
            seen = set()
            for s in shots:
                if s["stage"] in seen:
                    continue
                seen.add(s["stage"])
                out.append(f"- {s['stage']} ({s['at']}): ![{s['stage']}]({SHOTS}/{s['name']})")
        vs = versions(code, details=False)
        if vs:
            out += ["", f"## Versions ({len(vs)})", ""] + [f"- {x['at']}  {x['reason']}  (`{VERSIONS}/{x['name']}`)"
                                                           for x in vs[:10]]
        text = notes(code).strip()
        out += ["", "## Notes", "", text if text else "_(none yet - add what you learn: the problems, the fixes, who uses the file)_"]
        recent = history(code, limit=8)
        if recent:
            out += ["", "## Recent events", ""] + [f"- {e.get('at')}  {e.get('kind')}  " + _event_words(e)
                                                   for e in reversed(recent)]
        out += ["", f"_Written by the tool from the recording, the record checks and {HISTORY}; "
                    f"edit {NOTES}, never this file._", ""]
        _write_text(os.path.join(folder, README), "\n".join(out))
        return os.path.join(folder, README)
    except Exception:                                        # noqa: BLE001 - best effort
        return None


def _event_words(e):
    kind = e.get("kind")
    if kind == "run":
        return (f"ok {int(e.get('rows') or 0):,} rows" if e.get("ok") else f"FAILED {str(e.get('error', ''))[:90]}") + \
            (f" ({e.get('context')})" if e.get("context") else "")
    if kind in ("edit", "restore"):
        return "; ".join(e.get("changes") or [])[:160] or str(e.get("detail") or "")
    if kind == "check":
        return str(e.get("verdict") or "")
    return str(e.get("detail") or "")[:160]


def ensure(code):
    """Make sure a recorded screen has its folder, card and notes page. A new folder's history
    starts with what is already known: the past run reports and record checks (backfill)."""
    code = _code(code)
    folder = folder_for(code, create=True)
    if not os.path.isfile(os.path.join(folder, HISTORY)):
        backfill(code)
    if not os.path.isfile(os.path.join(folder, NOTES)):
        _write_text(os.path.join(folder, NOTES), NOTES_HEAD)
    write_readme(code)
    return folder


def _other_site_has(code):
    """Whether another G-MES site of this data root also records `code` (SEEG and HQ share codes)."""
    import gmes_site
    if not gmes_site.is_default():
        return True                                 # an HQ folder takes only runs that SAY hq
    root = os.path.dirname(gmes_profile.SCREENS_DIR)
    return any(os.path.isfile(os.path.join(gmes_site.site_root(root, s), "screens", f"{code}.json"))
               for s in gmes_site.known_sites(root))


def backfill(code):
    """Write the history a screen already has: every run report's result for it (oldest first) and
    every record check certificate. A report says which site it ran on since Phase 131; an older
    one is taken only when no other site has this code. Returns the number of events written."""
    import gmes_site
    code = _code(code)
    folder = folder_for(code, create=True)
    events = []
    try:
        ambiguous = _other_site_has(code)
        for path, site, started, results in reversed(run_reports()):     # oldest first
            if (site and site != gmes_site.current()) or (not site and ambiguous):
                continue
            for r in results:
                if str(r.get("screen") or "").upper() != code or r.get("status") not in ("ok", "failed"):
                    continue
                events.append({"at": started, "kind": "run", "ok": r.get("status") == "ok",
                               "rows": r.get("rows"), "error": (r.get("error") or None),
                               "files": [os.path.basename(f) for f in r.get("files") or []] or None,
                               "source": os.path.basename(path)})
    except Exception:                                   # noqa: BLE001 - best effort
        pass
    try:
        import gmes_recordcheck as rc
        cert_dir = rc.cert_dir()
        for name in sorted(os.listdir(cert_dir)):
            if not (name.upper().startswith(code + "_") and name.endswith(".json")):
                continue
            c = _read_json(os.path.join(cert_dir, name)) or {}
            events.append({"at": c.get("checked_at") or "", "kind": "check", "verdict": c.get("verdict"),
                           "source": name})
    except Exception:                                   # noqa: BLE001 - best effort
        pass
    events = [e for e in events if e.get("at")]
    events.sort(key=lambda e: e["at"])
    if events:
        with open(os.path.join(folder, HISTORY), "a", encoding="utf-8", newline="\n") as fh:
            for e in events:
                fh.write(json.dumps({k: v for k, v in e.items() if v is not None}, ensure_ascii=False) + "\n")
    else:
        open(os.path.join(folder, HISTORY), "a", encoding="utf-8").close()
    return len(events)


def ensure_all():
    """Every recording on this PC gets its folder (an existing library is only completed), and
    the catalogue is rewritten. Returns the number of screens."""
    n = 0
    for p in gmes_profile.known():
        if isinstance(p, dict) and p.get("learned") and p.get("screen"):
            try:
                ensure(p["screen"])
                n += 1
            except (OSError, ValueError):
                continue
    write_index()
    return n


def write_index():
    """INDEX.md: the catalogue of the library - one row per screen, like a warehouse list."""
    try:
        rows = catalogue()
        out = ["# Screen library", "", f"{len(rows)} screens. Each folder holds the screen's card (README.md), "
               "its notes, screenshots, versions and history.", "",
               "| Code | Title | Last run | Record check | Notes | Shots | Folder |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| {r['code']} | {r['title']} | {r['last_run'] or '-'} | {r['check'] or '-'} | "
                       f"{'yes' if r['has_notes'] else '-'} | {r['shots']} | [{r['folder']}](<{r['folder']}/{README}>) |")
        _write_text(os.path.join(library_root(), INDEX), "\n".join(out) + "\n")
    except Exception:                                        # noqa: BLE001 - best effort
        pass


def catalogue():
    """[{code, title, folder, last_run, last_ok, check, edited, has_notes, shots, versions, text}] for
    every recorded screen - `text` is what a search looks in (code, title, recipe, notes)."""
    certs = certificates()
    out = []
    for p in gmes_profile.known():
        if not isinstance(p, dict) or not p.get("learned"):
            continue
        code = str(p.get("screen") or "").upper()
        folder = folder_for(code)
        hist = history(code) if folder else []
        runs = [e for e in hist if e.get("kind") == "run"]
        cert = certs.get(code) or {}
        edited = next((e for e in reversed(hist) if e.get("kind") in ("edit", "restore")), None)
        note_text = notes(code) if folder else ""
        has_notes = bool(note_text.replace(NOTES_HEAD, "").strip())
        recipe = " ".join(f"{k} {v}" for k, v in recipe_lines(p))
        out.append({
            "code": code, "title": p.get("title") or "", "folder": os.path.basename(folder) if folder else "",
            "learned": p.get("learned") or "",
            "last_run": runs[-1]["at"] if runs else "", "last_ok": runs[-1].get("ok") if runs else None,
            "check": cert.get("verdict") or "", "check_at": cert.get("checked_at") or "",
            "edited": edited.get("at") if edited and str(edited.get("at")) > str(cert.get("checked_at") or "") else "",
            "has_notes": has_notes, "shots": len(screenshots(code)) if folder else 0,
            "versions": len(versions(code, details=False)) if folder else 0,
            "text": f"{code} {p.get('title') or ''} {recipe} {note_text}".lower(),
        })
    out.sort(key=lambda r: r["code"])
    return out


def search(query, rows=None):
    """Every screen whose code, title, recipe or notes hold all the words of `query`."""
    words = [w for w in str(query or "").lower().split() if w]
    rows = catalogue() if rows is None else rows
    return [r for r in rows if all(w in r["text"] for w in words)]


def dossier(code):
    """Everything about one screen, for a front end to show."""
    code = _code(code)
    profile = gmes_profile.load(code)
    if not profile:
        raise ValueError(f"{code} is not known on this PC")
    folder = ensure(code) if profile.get("learned") else folder_for(code)
    desc = describe(code)
    return {
        "code": code, "title": profile.get("title") or "", "folder": folder or "",
        "recorded": bool(profile.get("learned")), "learned": profile.get("learned") or "",
        "recipe": [{"name": k, "value": v} for k, v in recipe_lines(profile)],
        "status": [{"name": k, "value": v} for k, v in status_lines(code, profile)],
        "values": gmes_profile.last_values(profile),
        "options": [(o.get("label") if isinstance(o, dict) else str(o)) for o in profile.get("options") or []],
        "picks": list((profile.get("recipe") or {}).get("picks") or []),
        "period_column": bool((profile.get("recipe") or {}).get("period_column")),
        "export": profile.get("export") or "", "output_dir": profile.get("output_dir") or "",
        "distribute_to": list(profile.get("distribute_to") or []),
        "grid": profile.get("grid") or {},
        "recording": profile,
        "describe": desc, "drift": describe_drift(profile, desc),
        "screenshots": screenshots(code), "versions": versions(code),
        "history": list(reversed(history(code, limit=200))), "notes": notes(code),
    }
