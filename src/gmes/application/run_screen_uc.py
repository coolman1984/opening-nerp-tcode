"""One verified generic report run; no command parsing or session ownership."""
import os
import time
from datetime import datetime

from ..contracts import RunResult, RunSpec
from ..discovery.screen import open_screen
from ..export.excel import check_download, is_drm_protected
from ..export.naming import safe_name
from ..profiles import store
from ..profiles.drift import describe_change
from ..screens.filters import match_filter
from ..screens.grids import digits_only
from ..screens.organization import org_selection
from .. import paths


def default_output_dir():
    """Keep implicit exports out of source, install, and working directories."""
    return str(paths.exports_dir())


def _profile(code, screen, enabled, log):
    profile = store.load(code) if enabled else None
    if profile:
        problems = describe_change(profile, screen.info)
        if problems:
            for problem in problems:
                log(f"  changed  : {problem}")
            log("  learned  : ignored - reading this screen from scratch")
            return None
        log("  learned  : saved references match this screen")
    return profile


def _export(screen, grid, mode, out_dir, log):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = safe_name(screen.title or screen.code)
    files, excel_bytes, csv_rows = [], 0, 0
    if mode in ("xlsx", "csv", "both"):
        os.makedirs(out_dir, exist_ok=True)
    if mode in ("xlsx", "both"):
        downloaded = screen.export_excel(out_dir)
        final = os.path.join(out_dir, f"{name}_{stamp}.xlsx")
        if os.path.abspath(downloaded) != os.path.abspath(final):
            os.replace(downloaded, final)
        excel_bytes = check_download(final)
        files.append(final)
        drm = " [DRM - content unreadable by other programs]" if is_drm_protected(final) else ""
        log(f"  excel    : {os.path.basename(final)}  {excel_bytes / 1024:,.1f} KB{drm}")
    if mode in ("csv", "both"):
        result = screen.to_csv(grid, os.path.join(out_dir, f"{name}_{stamp}_data.csv"))
        # CSV may legitimately be smaller than Excel's 512-byte minimum.
        if not result.checked or not result.path or not os.path.isfile(result.path):
            raise RuntimeError("CSV export did not produce a checked file")
        files.append(result.path)
        csv_rows = result.row_count
        log(f"  csv      : {os.path.basename(result.path)}  {csv_rows} rows")
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
        try:
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
        except RuntimeError as error:
            if "no category tree" not in str(error):
                raise
            log("  division : this screen has no category tree - skipped")

    date_fields = []
    if spec.date_from or spec.date_to:
        date_fields = screen.set_date_range(spec.date_from, spec.date_to, profile)
        out["dates"] = tuple((flt.column or flt.control, value) for flt, value in date_fields)
        log(f"  dates    : {out['dates'] or 'this screen has no date field - skipped'}")
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
        dates = screen.date_like_columns(grid)
        if dates:
            sample = screen.rows(grid, limit=5)
            summary = {c: sorted({digits_only(row.get(c)) for row in sample["rows"]} - {""})
                       for c in dates[:4]}
            out["result_dates"] = summary
            log(f"  dates in : {summary} (set verify to make this a hard check)")

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
                    "to": spec.date_to or "", "sets": sets},
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
