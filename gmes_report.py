"""
Run ANY G-MES report by its UI number, without teaching the tool the screen
first.

    # Find a screen when you do not know its code
    python gmes_report.py find "production plan"

    # See what a screen offers - filters, options, grids, export
    python gmes_report.py describe P1112UM00

    # Apply everything but do NOT run the query, to check the setup first
    python gmes_report.py run P1112UM00 --division VD --date 20260908 --dry-run

    # Run it
    python gmes_report.py run P1112UM00 --division VD --date 20260908

    # Several screens, one after another
    python gmes_report.py run P1112UM00 P1111UM00 --division VD --days-back 1

    # Any discovered filter, by label, column or control name
    python gmes_report.py run P1112UM00 --division VD \
        --set "Production Order=011074232146" --set paramTecoYn=All

    # Left-panel dimensions that are not fields (see describe)
    python gmes_report.py run P1112UM00 --option PLANT --option "Create Date"

    # Refuse to export unless the rows really carry the date asked for
    python gmes_report.py run P1112UM00 --division VD --date 20260908 \
        --verify planYmd

All of the mechanism lives in gmes_core.py; this file is the command line
around it. Screens run SEQUENTIALLY and are isolated from each other - see
`gmes_core.run_many` for why that is a decision rather than a limitation.
"""
import argparse
import json
import sys

import cdp_common
import gmes_core as core


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


def cmd_describe(ws, screen_code):
    """Everything this screen offers, and how to address each of it."""
    screen = core.open_screen(ws, screen_code)
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
                print(f"   {o['label']:<28} {o['state']:<14} {o['kind']}")
            print("\n  These are dimensions, not fields: 'Plan Date' vs 'Create "
                  "Date' changes\n  which date the period means, and nothing "
                  "about the result looks wrong.")
    except Exception as e:
        print(f"\nLeft-panel options: could not be read ({e})")

    print(f"\nSet any filter with:  --set \"<label or column>=<value>\"")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["describe", "run", "find"])
    parser.add_argument("screens", nargs="+", metavar="UI",
                        help="one or more screen codes (e.g. P1112UM00), or "
                             "the text to search for with 'find'")
    parser.add_argument("--division", "--org", dest="division",
                        help="e.g. VD - ticked in whichever category tree holds it")
    parser.add_argument("--tree", help="name the category tree, when several hold the same entry")
    parser.add_argument("--date", help="YYYYMMDD or YYYY-MM-DD, applied to the screen's date fields")
    parser.add_argument("--days-back", type=int,
                        help="use the date N days ago instead of --date")
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
                        default="both")
    parser.add_argument("--output-dir", default=core.OUTPUT_DIR)
    parser.add_argument("--manifest", metavar="PATH",
                        help="write a JSON record of the run to this file")
    parser.add_argument("--dry-run", action="store_true",
                        help="apply everything and stop before Inquiry")
    parser.add_argument("--close-tabs", action="store_true",
                        help="close each screen's tab when it is done")
    parser.add_argument("--keep-open", action="store_true",
                        help="leave the automation browser running afterwards")
    args = parser.parse_args()

    try:
        date = core.date_from_args(args.date, args.days_back)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2

    sets = {}
    for item in args.set:
        if "=" not in item:
            print(f"ERROR: --set needs NAME=VALUE, got {item!r}")
            return 2
        key, value = item.split("=", 1)
        sets[key.strip()] = value.strip()

    if not core.sign_in():
        print("\nSign-in failed twice. Nothing was run.")
        return 1

    ws = core.connect()
    try:
        if args.command == "find":
            return cmd_find(ws, " ".join(args.screens))

        if args.command == "describe":
            for code in args.screens:
                cmd_describe(ws, code)
            return 0

        specs = [{"screen_code": code, "division": args.division, "date": date,
                  "sets": sets, "options": args.option, "export": args.export,
                  "out_dir": args.output_dir, "grid_name": args.grid,
                  "tree": args.tree, "verify": args.verify,
                  "dry_run": args.dry_run, "close_after": args.close_tabs}
                 for code in args.screens]

        results = core.run_many(ws, specs)
        ok = core.print_summary(results)

        if args.manifest:
            with open(args.manifest, "w", encoding="utf-8") as fh:
                json.dump({"date": date, "division": args.division,
                           "results": results}, fh, indent=2)
            print(f"  manifest: {args.manifest}")
        return 0 if ok == len(results) else 1
    finally:
        ws.close()
        if not args.keep_open and cdp_common.LAST_CHROME_PROCESS:
            try:
                cdp_common.LAST_CHROME_PROCESS.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
