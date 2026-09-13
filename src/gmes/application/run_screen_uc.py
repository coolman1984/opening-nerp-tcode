"""One verified generic report run; no command parsing or session ownership."""
import os
import time
import uuid
from datetime import datetime

from ..contracts import RunResult, RunSpec
from ..discovery.screen import open_screen
from ..export.excel import check_download, is_drm_protected
from ..export.naming import safe_name
from ..nexacro import popups
from ..profiles import store
from ..profiles.drift import describe_change
from ..screens.filters import match_filter
from ..screens.grids import digits_only
from ..screens.organization import org_selection
from .. import paths


def default_output_dir():
    """Keep implicit exports out of source, install, and working directories."""
    return str(paths.exports_dir())


def clear_notices(ws, log, when):
    """Close notice popups that are covering the screen, and say what is left.

    A notice is not only a sign-in event. G-MES raises one while a screen is
    open too, and it lands over the left panel: the Inquiry click is then
    swallowed by a window nobody asked about, and the run fails on a control
    that is present, visible and covered.

    Only popups positively identified as notices are closed. The Excel export
    dialog is a floating child window as well (GMES_SKILL #6), so this runs
    BEFORE an export is requested and never while one is in flight, and it
    reports anything it cannot name rather than clicking it."""
    closed, left = popups.close_notices(ws)
    if closed:
        log(f"  notices  : closed {', '.join(closed)} ({when})")
    if left:
        log(f"  popups   : left alone {', '.join(left)}")
    return closed, left


def _profile(code, screen, enabled, log):
    profile = store.load(code) if enabled else None
    if profile:
        problems = describe_change(profile, screen.info)
        if problems:
            for problem in problems:
                log(f"  changed  : {problem}")
            # A changed screen must not silently lose the user's saved intent.
            # Stop and require a deliberate fresh run after inspecting it.
            raise RuntimeError(
                "the remembered screen shape changed; refusing to replay saved settings")
        log("  learned  : saved references match this screen")
    return profile


def _download_workbook(screen, out_dir, log, attempts=3):
    """Ask for the workbook, and try again when the first attempt comes back
    empty-handed.

    Nobody is at the desk when the nightly job runs, so a single miss is the
    difference between a delivered report and an empty folder in the morning.
    Every observed miss so far has been recoverable and transient: a notice
    raised over the Excel icon, the screen losing focus to another tab, or
    the export dialog not having drawn its OK button yet.

    Each attempt re-establishes the three things the export depends on rather
    than waiting a while and hoping - the screen is brought back to the
    front, anything covering it is cleared, and a dialog left open by the
    previous attempt is dismissed - so a retry is a different attempt, not a
    repeat of the same one."""
    last = None
    for attempt in range(1, attempts + 1):
        # The visible screen is part of export identity; never press a
        # shell-level Excel button while a different report owns focus.
        if not screen.activate():
            raise RuntimeError("could not prove the report screen was active for Excel export")
        clear_notices(screen.ws, log, "before export")
        if attempt > 1:
            _clear_our_dialog(screen.ws, log)
        try:
            return screen.export_excel(out_dir)
        except RuntimeError as error:
            last = error
            if attempt == attempts:
                break
            log(f"  excel    : attempt {attempt} did not deliver a file ({error}); retrying")
    raise RuntimeError(f"the Excel export did not deliver a file in {attempts} attempts: {last}")


def _clear_our_dialog(ws, log):
    """Dismiss the export dialog our own failed attempt left on screen.

    Clicking the Excel icon again while that dialog is up fires a shortcut
    into an open dialog, which is exactly what CLAUDE.md 3.9 forbids. The
    dialog is ours - this attempt raised it - so dismissing it is not a
    guess. Anything still on screen that cannot be named stops the retry
    instead, because past an unknown window there is no diagnosis left."""
    dismissed, left = popups.close_dialogs(ws)
    if dismissed:
        log(f"  excel    : dismissed the dialog left by the last attempt "
            f"({', '.join(dismissed)})")
    unknown = [entry for entry in left if "(unknown)" in entry]
    if unknown:
        raise RuntimeError("refusing to request another export with an unrecognised "
                           f"window on screen: {', '.join(unknown)}")


def _export(screen, grid, mode, out_dir, log):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    name = safe_name(screen.title or screen.code)
    files, excel_bytes, csv_rows = [], 0, 0
    if mode in ("xlsx", "csv", "both"):
        os.makedirs(out_dir, exist_ok=True)
    try:
        if mode in ("xlsx", "both"):
            downloaded = _download_workbook(screen, out_dir, log)
            final = os.path.join(out_dir, f"{name}_{stamp}.xlsx")
            if os.path.abspath(downloaded) != os.path.abspath(final):
                os.replace(downloaded, final)
            # Own the delivered path before validation.  If validation fails,
            # the exception cleanup below must remove the unusable file too.
            files.append(final)
            excel_bytes = check_download(final)
            drm = " [DRM - content unreadable by other programs]" if is_drm_protected(final) else ""
            log(f"  excel    : {os.path.basename(final)}  {excel_bytes / 1024:,.1f} KB{drm}")
        if mode in ("csv", "both"):
            result = screen.to_csv(grid, os.path.join(out_dir, f"{name}_{stamp}_data.csv"))
            if not result.checked or not result.path or not os.path.isfile(result.path):
                raise RuntimeError("CSV export did not produce a checked file")
            files.append(result.path)
            csv_rows = result.row_count
            log(f"  csv      : {os.path.basename(result.path)}  {csv_rows} rows")
    except Exception:
        for path in files:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return tuple(files), excel_bytes, csv_rows


def run_screen(ws, spec: RunSpec, log=print) -> RunResult:
    """Open, apply explicit values, inquire, verify, export, then remember.

    Exceptions stop this run before later actions. The sequential batch use
    case owns failure reporting. Dates are already decided by the caller.
    """
    if spec.export not in ("xlsx", "csv", "both", "none"):
        raise ValueError(f"unknown export format: {spec.export}")
    started = time.monotonic()
    code = spec.screen_code.strip().upper()
    sets = dict(spec.sets)
    log(f"\n{'=' * 70}\n{code}\n{'=' * 70}")
    screen = open_screen(ws, code, log=log)
    out = dict(screen=code, ok=False, title=screen.title, menu_id=screen.menu_id,
               window=screen.win_id, dry_run=spec.dry_run)
    log(f"  screen   : {screen.title}  [{screen.menu_id}]")
    # A notice raised while this screen was opening covers the controls the
    # rest of this function is about to click.
    clear_notices(ws, log, "screen open")
    profile = _profile(code, screen, spec.use_profile, log)
    out["used_profile"] = bool(profile)
    grid = screen.grid(spec.grid_name or ((profile or {}).get("grid") or {}).get("dataset"))
    log(f"  filters  : {len(screen.filters)} bound, {len(screen.unbound)} unbound")
    options = spec.options or tuple((profile or {}).get("options") or ())
    applied_options = []
    for label in options:
        outcome = screen.set_option(label)
        applied_options.append(outcome)
        log(f"  option   : {outcome}")
    if options:
        grid = screen.grid(spec.grid_name)
    out["grid"] = f"{grid.name} -> {grid.dataset}"
    out["options"] = tuple(applied_options)
    log(f"  results  : {grid.dataset} (grid {grid.name})")

    if spec.division:
        picked = screen.select_org(spec.division, tree=spec.tree,
                                   prefer=((profile or {}).get("division") or {}).get("dataset"))
        names = ", ".join(sorted({entry["name"] for entry in picked["ticked"]}))
        out["division"] = names
        detail = names
        if picked.get("confirmed"):
            detail += f" (screen confirms {picked['confirmed']})"
        cleared = sorted(set(picked.get("cleared") or []))
        if cleared:
            detail += f" (unticked {len(cleared)}: {', '.join(cleared[:4])})"
        log(f"  division : {detail}")

    date_fields = []
    if spec.date_from or spec.date_to:
        date_fields = screen.set_date_range(spec.date_from, spec.date_to, profile)
        out["dates"] = tuple((flt.column or flt.control, value) for flt, value in date_fields)
        if not date_fields:
            raise RuntimeError("the requested period was not applied to any field")
        log(f"  dates    : {out['dates']}")
    keep = {flt.column for flt, _value in date_fields}
    for key in sets:
        matched = match_filter(screen.info, key)
        if matched is not None and not isinstance(matched, list):
            keep.add(matched.column)
    out["cleared"] = tuple(screen.clear_stale(keep))
    if out["cleared"]:
        log(f"  cleared  : leftover {', '.join(out['cleared'])}")
    applied = {}
    for key, value in sets.items():
        flt, actual = screen.set_filter(key, value)
        applied[flt.label or flt.column or flt.control] = actual
        log(f"  filter   : {flt.label or flt.column} {'set' if flt.bound else 'typed'} to {actual!r}")
    out["applied"] = applied
    if spec.dry_run:
        log("  dry run  : everything above was applied; Inquiry NOT clicked")
        return _complete(out, screen, started, log)

    effective_division = spec.division or ""
    seen_org = org_selection(ws)
    if seen_org.get("found") and seen_org.get("org"):
        effective_division = seen_org["org"]
        if not spec.division:
            log(f"  division : none asked for; the screen has {effective_division} in effect")
    clear_notices(ws, log, "before inquiry")
    rows = screen.inquiry(grid)
    out["rows"] = rows
    log(f"  inquiry  : {rows} rows in {time.monotonic() - started:.1f}s")
    if rows == 0:
        raise RuntimeError("the query returned no rows - nothing exported")
    if spec.verify:
        column, expected = spec.verify
        expected = expected or spec.date_from
        seen = screen.verify_column(grid, column.strip(), expected, strict=True)
        out["verified"] = {column.strip(): seen}
        log(f"  verified : {column.strip()} = {seen}")
    elif spec.date_from:
        raise RuntimeError("a date-constrained run requires --verify COLUMN[=VALUE]")

    out["files"], out["excel_bytes"], out["csv_rows"] = _export(
        screen, grid, spec.export, spec.out_dir or default_output_dir(), log)
    if spec.close_after:
        out["closed"], detail = screen.close()
        log(f"  tab      : {detail}")
    if spec.use_profile:
        saved = store.save(
            code, screen.title, screen.menu_id, screen.info,
            from_ref=date_fields[0][0] if date_fields else None,
            to_ref=date_fields[1][0] if len(date_fields) > 1 else None,
            division=screen.last_tree, grid=grid, rows=rows, options=options,
            values={"division": effective_division, "from": spec.date_from or "",
                    "to": spec.date_to or "", "verify": (spec.verify or ("", None))[0],
                    "sets": sets},
            command=f"--division {spec.division} --from {spec.date_from} --to {spec.date_to}")
        out["profile"] = str(saved)
        log(f"  learned  : saved to {os.path.basename(saved)}")
    return _complete(out, screen, started, log)


def _complete(out, screen, started, log):
    for warning in screen.warnings:
        log(f"  warning  : {warning}")
    return RunResult(**{**out, "ok": True, "warnings": tuple(screen.warnings),
                        "duration_s": round(time.monotonic() - started, 1)})


def print_summary(results, log=print):
    log(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    log(f"  {'SCREEN':<14} {'STATUS':<9} {'ROWS':>7}  FILES / ERROR")
    for result in results:
        if result.ok:
            files = ", ".join(os.path.basename(path) for path in result.files) or "-"
            log(f"  {result.screen:<14} {'ok':<9} {result.rows:>7}  {files}")
        else:
            log(f"  {result.screen:<14} {'FAILED':<9} {'-':>7}  {result.error}")
    succeeded = sum(result.ok for result in results)
    log(f"\n  {succeeded}/{len(results)} succeeded")
    return succeeded
