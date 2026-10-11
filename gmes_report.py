"""
Run ANY G-MES report by its UI number, without teaching the tool the screen
first.

    # Find a screen when you do not know its code
    python gmes_report.py find "production plan"

    # See what a screen offers - filters, options, grids, export
    python gmes_report.py describe P1112UM00

    # Apply everything but do NOT run the query, to check the setup first
    python gmes_report.py run P1112UM00 --division VD --from 20260909 \
        --to 20260909 --dry-run

    # Run it. Both dates are yours - nothing is calculated from today.
    python gmes_report.py run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd

    # Several screens, one after another
    python gmes_report.py run P1112UM00 P1111UM00 --division VD \
        --from 20260901 --to 20260910 --verify planYmd

    # Any discovered filter, by label, column or control name
    python gmes_report.py run P1112UM00 --division VD \
        --set "Production Order=011074232146" --set paramTecoYn=All

    # Left-panel dimensions that are not fields (see describe)
    python gmes_report.py run P1112UM00 --option PLANT --option "Create Date"

    # Refuse to export unless the rows really carry the date asked for
    python gmes_report.py run P1112UM00 --division VD --from 20260909 \
        --to 20260909 --verify planYmd

    # RECORD a screen and prove it - the same record check as GMES Automation's
    # "Record + check": the run, a BARE replay, the batch planner, judged item by
    # item, kept as a certificate. A 6-digit --from/--to is a whole month.
    python gmes_report.py record P1112UM00 --division VD --date 20260929 --verify planYmd
    python gmes_report.py record Q321KUM00 --division "MAIN Part" --set fromDt=202609 --set toDt=202609

    # Prove an earlier recording again (one bare replay, judged, certificate)
    python gmes_report.py check P1112UM00 R3220UM00

    # No browser: what is recorded and how its last check went; confirm a typed
    # period seen on the G-MES screen; forget a recording
    python gmes_report.py status
    python gmes_report.py confirm Q321KUM00
    python gmes_report.py forget P1112UM00

All of the mechanism lives in gmes_core.py (the record check in
gmes_recordcheck.py - the window runs the very same functions); this file is the
command line around it. Screens run SEQUENTIALLY and are isolated from each
other - see `gmes_core.run_many` for why that is a decision rather than a
limitation.
"""
import argparse
import json
import os
import re
import sys
import tempfile

import cdp_common
import gmes_core as core
import gmes_site
import gmes_twin

COMMANDS = ("describe", "run", "find", "record", "check", "confirm", "forget", "status")
OFFLINE = ("confirm", "forget", "status")          # no browser, no sign-in


def cmd_status():
    """Every recording, its status, last run and record check - like the window's
    Reports page. Offline."""
    import gmes_batch
    import gmes_library as library
    import gmes_profile
    import gmes_recordcheck as rc
    profiles = gmes_profile.known()
    last = library.last_result_by_code(library.run_history())
    certs = rc.certificates()
    print(f"\n{len(profiles)} known screen(s); record checks in {rc.cert_dir()}\n")
    print(f"  {'CODE':<11} {'STATUS':<20} {'RECORD CHECK':<22} TITLE")
    print("  " + "-" * 92)
    for p in profiles:
        card = library.report_card(p, last.get(str(p.get("screen", "")).upper()))
        cert = certs.get(card["code"].upper()) or {}
        check = (f"{cert['verdict']} {cert.get('checked_at', '')[:10]}" if cert.get("verdict")
                 else ("not checked yet" if p.get("learned") else "not recorded here"))
        print(f"  {card['code']:<11} {card['status']:<20} {check:<22} {card['title'][:40]}")
    gmes_batch.warn_unreadable()
    report = gmes_twin.sync(dry_run=True)
    print("\nGMES Automation (the window): " + (report.skipped or (
        "at the same level - same recordings, batches, record checks and history"
        if report.in_sync else
        f"{len(report.actions)} item(s) differ, {len(report.conflicts)} conflict(s) - "
        "python gmes_twin.py status")))
    return 0


def cmd_forget(codes, yes=False):
    import gmes_profile
    import gmes_recordcheck as rc
    for code in codes:
        code = rc.normalise_code(code)
        if not os.path.isfile(gmes_profile.path_for(code)):
            print(f"{code}: not recorded on this PC - nothing to forget.")
            continue
        if not yes:
            answer = input(f"Forget the recording of {code}? It is removed from the window "
                           "(GMES Automation) too. Type y to confirm: ")
            if answer.strip().lower() != "y":
                print(f"{code}: kept.")
                continue
        gmes_profile.forget(code)
        print(f"{code}: forgotten (the window forgets it at its next sync; a copy is kept in "
              "screens\\.twin\\backup).")
    return 0


def cmd_confirm(codes):
    import gmes_recordcheck as rc
    ok = True
    for code in codes:
        try:
            result = rc.confirm_from_certificate(code)
        except rc.Problem as e:
            print(f"{rc.normalise_code(code)}: {e}")
            ok = False
            continue
        print("\n".join(rc.check_lines(result)))
    return 0 if ok else 1


def record_spec(args, date_from, date_to, sets):
    import gmes_recordcheck as rc
    return rc.build_spec(args.screens[0], args.division or "", date_from or "", date_to or "", sets,
                         args.option, args.grid or "", args.verify or "", args.export or "xlsx",
                         args.output_dir or "", args.tree or "")


def cmd_record(ws, args, date_from, date_to, sets):
    """Record + record check, exactly as the window's Record page does it."""
    import gmes_recordcheck as rc
    spec = record_spec(args, date_from, date_to, sets)
    if args.distribute_to:
        spec["distribute_to"] = list(args.distribute_to)
    if args.dry_run:
        out = rc.record(ws, spec, dry_run=True)
        print("\nDry run: everything applied, stopped before Inquiry - "
              + ("ok." if out.get("ok") else f"FAILED: {out.get('error')}"))
        return 0 if out.get("ok") else 1
    result = rc.record_and_check(ws, spec)
    print("\n" + "\n".join(rc.check_lines(result)))
    return 0 if result["verdict"] != "FAILED" else 1


def cmd_check(ws, codes):
    import gmes_recordcheck as rc
    worst = 0
    for code in codes:
        try:
            result = rc.recheck(ws, code)
        except rc.Problem as e:
            print(f"\n{rc.normalise_code(code)}: {e}")
            worst = 1
            continue
        print("\n" + "\n".join(rc.check_lines(result)))
        if result["verdict"] == "FAILED":
            worst = 1
    return worst


def cmd_find(ws, query):
    import gmes_open_screen
    info = gmes_open_screen.catalogue(ws, query)
    if not info.get("found"):
        print("The screen catalogue is not loaded yet - is G-MES signed in?")
        return 1
    rows = info.get("rows", [])
    print(f"\n{info['total']} screens; {len(rows)} match {query!r}:\n")
    gmes_open_screen.print_rows(rows)
    return 0


def cmd_describe(ws, screen_code, close_tabs=False):
    """Everything this screen offers, and how to address each of it.

    `--close-tabs` is a global flag every command accepts, but this one used
    to ignore it silently - describe opens a work screen (`core.open_screen`)
    and never closed it, so a multi-screen `describe --close-tabs` still left
    every one of them open, feeding the NEXT screen's unchanged-result and
    shape checks a session that already has stale windows sitting in it
    (HISTORY.md Open Item 49)."""
    screen = core.open_screen(ws, screen_code)
    try:
        return _describe_body(screen)
    finally:
        if close_tabs:
            ok, detail = screen.close()
            print(f"\ntab      : {detail}")


def _describe_body(screen):
    info = screen.info

    print(f"\n{screen.title}   [{screen.code} / {screen.menu_id}]")
    print(f"Window              : {screen.win_id}")
    print(f"Inquiry button      : {'yes' if info['hasInquiry'] else 'no'}")
    print(f"Excel download      : {'yes' if info['hasExcel'] else 'no'}")

    grids = info.get("grids", [])
    if grids:
        print(f"\nResult grids ({len(grids)}) - name one with --grid:\n")
        chosen, rivals = core.choose_grid(info)
        for g in grids:
            ds = info["datasets"].get(g["dataset"], {})
            mark = "*" if chosen and g["name"] == chosen["name"] else " "
            seen = "" if g["visible"] else "   (not on screen)"
            print(f"  {mark} {g['name']:<20} {g['dataset']:<26} "
                  f"{ds.get('cols', '?')} cols, {ds.get('rows', '?')} rows now{seen}")
        print("\n  ('*' = what a run would use)")
        if rivals:
            print("  WARNING: more than one grid is comparable in size here. "
                  "Pass --grid to be certain which one is exported.")

    filters = info.get("filters", [])
    print(f"\nFilters bound to a dataset ({len(filters)}):\n")
    if filters:
        print(f"   {'LABEL':<26} {'COLUMN':<22} {'NOW':<14} CONTROL")
        print("  " + "-" * 84)
        for f in sorted(filters, key=lambda x: (not x["visible"], x["label"])):
            mark = " " if f["visible"] else "."
            date_mark = "  <- date" if core.is_date_field(f) else ""
            print(f" {mark} {(f['label'] or '-'):<26} {f['column']:<22} "
                  f"{(f['value'] or '')[:13]:<14} {f['control']}{date_mark}")
        print("\n  ('.' = bound but not currently visible on screen)")

    unbound = info.get("unbound", [])
    if unbound:
        print(f"\nVisible inputs this screen does NOT bind ({len(unbound)}) - "
              "these are typed into:\n")
        for u in unbound:
            print(f"   {(u['label'] or '-'):<26} {u['control']:<22} "
                  f"{(u['value'] or '')[:13]:<14} {u['form']}")

    if not filters and not unbound:
        print("\n  This screen exposes no filters at all. It can still be "
              "opened, run and exported.")

    frm, to, singles = core.date_targets(info)
    dates = [f["column"] for f in (frm, to) if f] or [f["column"] for f in singles]
    print(f"\n--date would set : {', '.join(dates) if dates else '(nothing - no date field)'}")

    try:
        trees = [t for t in screen.trees() if t["settable"]]
        if trees:
            print(f"\nCategory trees ({len(trees)}) - --division ticks one of these:\n")
            for t in trees:
                ticked = f"  ticked now: {t['checked']}" if t["checked"] else ""
                print(f"   {t['form']:<28} {t['dataset']:<30} {t['rows']} rows{ticked}")
                print(f"   {'':<28} e.g. {', '.join(t['names'][:8])}")
    except Exception as e:
        print(f"\nCategory trees: could not be read ({e})")

    try:
        opts = screen.options()
        if opts:
            print(f"\nLeft-panel options ({len(opts)}) - set with --option:\n")
            for o in opts:
                # `state` (selected/not selected/checked/unchecked) and
                # whether the control can be clicked AT ALL right now are
                # separate axes - a screen-state precondition (e.g. a
                # different category tab) can leave an option genuinely
                # disabled while it still shows as "not selected"
                # (HISTORY.md Phase 71.2). Shown separately so --option
                # never has to discover this only after an unexplained
                # "could not prove selected" failure.
                state = o["state"] if o.get("enabled", True) else \
                    f"{o['state']} (disabled)"
                # The key is shown because it is what --option should be given
                # and what a profile stores: the label is whatever language
                # G-MES is rendering today, and the same screen has been seen
                # in both (HISTORY.md Phase 76).
                key = core.option_key(o.get("name"))
                print(f"   {o['label']:<22} {'[' + key + ']':<18} "
                      f"{state:<24} {o['kind']}")
            print("\n  These are dimensions, not fields: 'Plan Date' vs 'Create "
                  "Date' changes\n  which date the period means, and nothing "
                  "about the result looks wrong.")
    except Exception as e:
        print(f"\nLeft-panel options: could not be read ({e})")

    print(f"\nSet any filter with:  --set \"<label or column>=<value>\"")
    return 0


def write_manifest_safely(path, date_from, date_to, division, results):
    """Write the optional `--manifest` JSON without letting its failure
    overturn a run that already succeeded.

    The manifest is written AFTER `core.print_summary()` has already told the
    console every file that was really delivered - a run's real result. A
    manifest write failure (missing parent directory, permission denial, the
    destination being a directory, an `os.replace()` that cannot cross
    filesystems) used to `raise` past the caller's own `return 0 if ok ==
    len(results) else 1`, so a fully successful export could still exit
    non-zero with a raw traceback - the exact "delivered file reported as a
    failure" class `gmes_core.run_screen()`'s own profile-save step is
    already isolated to prevent (HISTORY.md, `gmes_core.py` around the "only
    now is any of this worth remembering" comment)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".gmes-manifest-", suffix=".partial",
                                         dir=directory)
    except OSError as e:
        print(f"  warning  : the manifest could not be written ({e}) - "
              "the results above are still real")
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"from": date_from, "to": date_to,
                      "division": division, "results": results}, fh, indent=2)
        os.replace(temporary, path)
    except Exception as e:                                   # noqa: BLE001
        try:
            os.unlink(temporary)
        except OSError:
            pass
        print(f"  warning  : the manifest could not be written ({e}) - "
              "the results above are still real")
        return
    print(f"  manifest: {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=list(COMMANDS))
    parser.add_argument("screens", nargs="*", metavar="UI",
                        help="one or more screen codes (e.g. P1112UM00), or "
                             "the text to search for with 'find' (none for 'status')")
    parser.add_argument("--yes", action="store_true",
                        help="forget: do not ask for confirmation")
    parser.add_argument("--division", "--org", dest="division",
                        help="e.g. VD - ticked in whichever category tree holds it")
    parser.add_argument("--tree", help="name the category tree, when several hold the same entry")
    parser.add_argument("--from", dest="date_from", metavar="YYYYMMDD",
                        help="start of the period. Typed by you - no date is "
                             "ever worked out from today")
    parser.add_argument("--to", dest="date_to", metavar="YYYYMMDD",
                        help="end of the period")
    parser.add_argument("--date", help="shorthand for the same --from and --to")
    parser.add_argument("--relearn", action="store_true",
                        help="forget what was learned about this screen and "
                             "read it from scratch")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="any discovered filter, by label, column or control name")
    parser.add_argument("--option", action="append", default=[], metavar="LABEL",
                        help='a left-panel option by its label, e.g. PLANT, '
                             '"Create Date", Prod, "Including Past Org."')
    parser.add_argument("--grid", help="which result grid to read and export, "
                                       "when the screen has more than one")
    parser.add_argument("--verify", metavar="COLUMN[=VALUE]",
                        help="refuse to export unless the result rows carry this "
                             "value (defaults to --date)")
    parser.add_argument("--export", choices=["xlsx", "csv", "both", "none"],
                        default=None,
                        help="default: xlsx (Excel only), or a screen's own "
                             "pinned choice if it has one. 'both' now means "
                             "xlsx too - a CSV needs 'csv' (Phase 98.1). "
                             "Passing this explicitly on a successful run PINS "
                             "it for every future replay of this screen, until "
                             "a run explicitly names 'xlsx' again")
    parser.add_argument("--output-dir", default=None,
                        help=f"default: {core.OUTPUT_DIR}, or a screen's own "
                             "pinned folder if it has one. Passing this "
                             "explicitly on a successful run PINS it for "
                             f"every future replay of this screen, until a "
                             f"run explicitly names {core.OUTPUT_DIR!r} again")
    parser.add_argument("--distribute-to", action="append", default=[], metavar="PATH",
                        help="an EXTRA folder to also copy this run's file(s) to, "
                             "on top of --output-dir, never instead of it. Give it "
                             "more than once for more than one folder. Passing this "
                             "explicitly on a successful run PINS the whole list for "
                             "every future replay of this screen, until a run "
                             "explicitly passes it again with a different list")
    parser.add_argument("--pick", action="append", default=[], metavar="LABEL=VALUE",
                        help="choose an entry of a search-picker filter that has no "
                             "text to type (Defect Cause = a list in a popup): "
                             "--pick \"Defect Cause=Folder Function Defect\". Saved "
                             "with the screen (HISTORY.md Phase 110)")
    parser.add_argument("--click-cell", action="append", default=[],
                        metavar="GRID|HEADER=TEXT;...|COLUMN",
                        help="after Inquiry, click the number where the ONE row "
                             "matching the header=text pairs meets COLUMN: "
                             "--click-cell \"grdTrend|Code=Total;category=Deft. Qty|Total\"")
    parser.add_argument("--result-grid", metavar="NAME",
                        help="the table the click fills - it is verified and exported "
                             "as the report (e.g. GridStatus)")
    parser.add_argument("--export-via", metavar="GRID|MENU>ITEM",
                        help="export by right-clicking a table instead of the toolbar "
                             "Excel button: --export-via \"GridStatus|Export>Save Excel(General)\"")
    parser.add_argument("--period-column", action="store_true",
                        help="put the typed period and the division (Period From / Period To / Division) as the first CSV "
                             "columns - for a result whose rows do not say which period they are "
                             "(R3220 Line / Part views). Saved with the screen (HISTORY.md Phase 130)")
    parser.add_argument("--manifest", metavar="PATH",
                        help="write a JSON record of the run to this file")
    parser.add_argument("--dry-run", action="store_true",
                        help="apply everything and stop before Inquiry")
    parser.add_argument("--close-tabs", action="store_true",
                        help="close each screen's tab when it is done")
    parser.add_argument("--keep-open", action="store_true",
                        help="leave the automation browser running afterwards")
    parser.add_argument("--site", default=None, choices=sorted(gmes_site.SITES),
                        help="which G-MES: seeg (default, SEEG's own) or hq (HQ G-MES, "
                             "several factories). Each keeps its own recordings "
                             "(HISTORY.md Phase 130)")
    args = parser.parse_args(argv)
    # Before anything reads a recording: the site decides which ones exist.
    site = gmes_site.activate(args.site)
    if not gmes_site.is_default(site):
        print(f"site     : {gmes_site.label(site)}  ({gmes_site.url(site)})")

    # GMES_Workflow.bat's argument branch already runs
    # `python gmes_report.py run %*` - typing "run" again
    # (GMES_Workflow.bat run P1112UM00 ...) makes THIS parser see "run" a
    # second time, where it lands in `screens` (nargs="+") as if it were a
    # screen code. The batch/CSV cascade that followed ("RUN not found",
    # then every real screen skipped as "previous screen left an unknown
    # state") was confusing enough that it looked like a deeper failure.
    # Caught here, once, with a direct fix rather than left to cascade.
    if args.command == "run" and args.screens and args.screens[0].strip().lower() == "run":
        print("ERROR: that extra 'run' is not a screen code.")
        print("       GMES_Workflow.bat already adds 'run' for you - use:")
        print(f"           GMES_Workflow.bat {' '.join(args.screens[1:])}")
        print("       'run' is only typed when calling gmes_report.py directly, e.g.:")
        print(f"           python gmes_report.py run {' '.join(args.screens[1:])}")
        return 2
    if not args.screens and args.command != "status":
        print(f"ERROR: '{args.command}' needs at least one screen code"
              + (" (or the words to search for)" if args.command == "find" else ""))
        return 2
    if args.command == "record" and len(args.screens) != 1:
        print("ERROR: record one screen at a time - each one gets its own record check.")
        return 2
    if args.command == "record" and (args.pick or args.click_cell or args.result_grid
                                     or args.export_via or args.manifest or args.period_column):
        print("ERROR: --pick / --click-cell / --result-grid / --export-via / --manifest are run "
              "options. Record such a screen with 'run --relearn', then prove it with 'check'.")
        return 2

    # The window beside this tool may have recorded something newer since the last
    # run, and what this command learns must reach it (CLAUDE.md 0a, HISTORY.md 123).
    twin = gmes_twin.Announcer(print)          # a conflict is said once
    twin()
    try:
        return _main(args)
    finally:
        twin()


def _main(args):
    if args.command == "status":
        return cmd_status()
    if args.command == "forget":
        return cmd_forget(args.screens, yes=args.yes)
    if args.command == "confirm":
        return cmd_confirm(args.screens)

    # A Month, as the window's Record page means it: a 6-digit --from/--to (or --date)
    # is the whole month, first to last day (gmes_recordcheck.month_bounds,
    # HISTORY.md Phase 121 - the engine takes only days).
    if args.command == "record":
        lo = args.date_from or args.date or ""
        hi = args.date_to or args.date or lo
        if re.fullmatch(r"\d{6}", lo or "") and re.fullmatch(r"\d{6}", hi or ""):
            import gmes_recordcheck as rc
            args.date_from, args.date_to = rc.month_bounds(lo, hi)
            args.date = None

    # Both dates are the caller's own. Nothing here calculates one, and both
    # are checked while the user can still fix them: "2026-09-07" written
    # through unchecked reaches a field that stores YYYYMMDD and the query
    # then quietly answers a different question.
    try:
        date_from = core.normalise_date(args.date_from or args.date)
        date_to = core.normalise_date(args.date_to or args.date)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2
    if bool(date_from) != bool(date_to):
        print("ERROR: give both --from and --to (or --date for a single day).")
        return 2
    if date_from and date_from > date_to:
        print("ERROR: --from cannot be after --to.")
        return 2
    if args.command in ("run", "record") and date_from and not args.verify and not args.dry_run:
        # --dry-run never clicks Inquiry (gmes_core.run_screen() returns
        # before verification is even reached), so there is nothing yet to
        # verify - the check exists to stop an unchecked EXPORT of the wrong
        # day, not to gate a setup check that exports nothing at all.
        print("ERROR: a date-constrained run needs --verify COLUMN[=VALUE].")
        return 2

    sets = {}
    for item in args.set:
        if "=" not in item:
            print(f"ERROR: --set needs NAME=VALUE, got {item!r}")
            return 2
        key, value = item.split("=", 1)
        sets[key.strip()] = value.strip()

    if args.command == "record":
        # The window's own check of the scope, BEFORE a browser or a sign-in is spent
        import gmes_recordcheck as rc
        problems = rc.check_spec(record_spec(args, date_from, date_to, sets))
        if problems:
            for p in problems:
                print(f"ERROR: {p}")
            return 2

    # Two of these processes sharing one Chrome/CDP session interfere with
    # each other silently (HISTORY.md: a concurrent run's screen-open landed
    # on a row the OTHER run's screen had made temporarily not visible, and
    # failed with a confusing "grid row not visible" - nothing about that
    # message says "another run is using this browser"). Refuse up front,
    # with a cause a person can actually act on, instead of leaving it to
    # whatever downstream step happens to collide first.
    try:
        lock_token = core.acquire_run_lock()
    except core.RunLocked as e:
        print(f"ERROR: {e}")
        return 1

    try:
        if not core.sign_in():
            print("\nSign-in failed twice. Nothing was run.")
            return 1

        ws = core.connect()
        try:
            if args.command == "find":
                return cmd_find(ws, " ".join(args.screens))

            if args.command == "record":
                return cmd_record(ws, args, date_from, date_to, sets)

            if args.command == "check":
                return cmd_check(ws, args.screens)

            if args.command == "describe":
                # Unlike `run` (core.run_many isolates each screen and reports
                # failures cleanly via print_summary), describe had nothing
                # catching a bad screen code here - a typo in the middle of a
                # multi-screen `describe` dumped a raw traceback and aborted
                # every screen after it, instead of the same clean, actionable
                # message open_screen() already raises.
                ok = True
                for code in args.screens:
                    try:
                        cmd_describe(ws, code, close_tabs=args.close_tabs)
                    except Exception as e:
                        print(f"\n{code}: {e}")
                        ok = False
                return 0 if ok else 1

            # --relearn used to gmes_profile.forget() every screen's profile
            # HERE, before any of them had even been opened - a batch of
            # several screens where the FIRST one's relearn attempt failed
            # (the screen changed unexpectedly, a transient error, anything)
            # still lost every OTHER screen's profile too, since the delete
            # loop ran for all of them upfront, before run_many() ever
            # attempted any. trust_profile=False (run_screen()'s own parameter,
            # HISTORY.md Phase 66.2/67) gets the same practical effect - the
            # old profile is not loaded or trusted - without deleting anything:
            # it is only ever superseded by that SAME screen's own successful
            # save, never lost to a different screen's failure.
            if args.relearn:
                print(f"  relearning: {', '.join(c.upper() for c in args.screens)}")

            try:
                recipe = core.build_recipe(args.pick, args.click_cell, args.result_grid,
                                           args.export_via, args.period_column)
            except ValueError as e:
                print(f"ERROR: {e}")
                return 2
            if recipe and len(args.screens) != 1:
                print("ERROR: --pick / --click-cell / --result-grid / --export-via belong "
                      "to one screen's recording - name exactly one screen")
                return 2

            specs = [{"screen_code": code, "division": args.division,
                      "date_from": date_from, "date_to": date_to,
                      "sets": sets, "options": args.option, "export": args.export,
                      "out_dir": args.output_dir, "distribute_to": args.distribute_to or None,
                      "grid_name": args.grid,
                      "tree": args.tree, "verify": args.verify,
                      "dry_run": args.dry_run, "close_after": args.close_tabs,
                      "trust_profile": not args.relearn, "recipe": recipe}
                     for code in args.screens]

            results = core.run_many(ws, specs)
            ok = core.print_summary(results)

            if args.manifest:
                write_manifest_safely(args.manifest, date_from, date_to,
                                      args.division, results)
            return 0 if ok == len(results) else 1
        finally:
            ws.close()
            cdp_common.stop_if_started_here(args.keep_open)
    finally:
        core.release_run_lock(lock_token)


if __name__ == "__main__":
    sys.exit(main())
