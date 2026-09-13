"""The unified G-MES command-line surface.

Parsing and rendering live here. Each command makes one application operation;
the application owns authentication, CDP connection, capability, and cleanup.
"""
import argparse
import os
import sys

from ..application import facade as application


def _parser():
    parser = argparse.ArgumentParser(prog="gmes", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("version", help="show the standalone package version")
    login = sub.add_parser("login", help="sign in to G-MES")
    login.add_argument("--assist", action="store_true")
    login.add_argument("--refresh-profile", action="store_true")
    credentials = sub.add_parser("credentials", help="explicitly set the local encrypted G-MES credential")
    credentials_sub = credentials.add_subparsers(dest="credentials_command", required=True)
    credentials_sub.add_parser("set", help="prompt for and save the local DPAPI credential")
    sub.add_parser("migrate", help="explicitly copy a legacy credential store if needed")
    sub.add_parser("doctor", help="read-only environment and runtime readiness report")
    sub.add_parser("workflow", help="guided interactive workflow using the same execution engine")
    run = sub.add_parser("run", help="run one or more screens sequentially")
    run.add_argument("screens", nargs="+", metavar="UI")
    run.add_argument("--division", "--org", dest="division")
    run.add_argument("--tree")
    run.add_argument("--from", dest="date_from")
    run.add_argument("--to", dest="date_to")
    run.add_argument("--date")
    run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--option", action="append", default=[])
    run.add_argument("--grid")
    run.add_argument("--verify", metavar="COLUMN[=VALUE]")
    run.add_argument("--export", choices=("xlsx", "csv", "both", "none"), default="both")
    run.add_argument("--output-dir")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--close-tabs", action="store_true")
    run.add_argument("--no-profile", action="store_true")
    run.add_argument("--relearn", action="store_true",
                     help="ignore what was learned about this screen and record it again")
    data = sub.add_parser("data", help="inspect a Nexacro dataset")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    forms = data_sub.add_parser("forms", help="list forms and datasets")
    read = data_sub.add_parser("read", help="read rows from a dataset")
    read.add_argument("screen_code")
    read.add_argument("dataset")
    read.add_argument("--limit", type=int, default=20,
                      help="number of rows (use -1 only when a full read is intended)")
    read.add_argument("--offset", type=int, default=0)
    return parser


class _WorkflowInputClosed(Exception):
    """The interactive operator ended input; this is a normal stop."""


def _ask(prompt, default=""):
    shown_default = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{shown_default}: ").strip()
    except EOFError as error:
        raise _WorkflowInputClosed() from error
    return value or default


def _profile_values(profile):
    values = dict((profile or {}).get("values") or {})
    values["sets"] = dict(values.get("sets") or {})
    return values


def _filter_name(flt):
    """The name the engine resolves without ambiguity: the stored column for
    a bound control, the control's own name for one the screen types into."""
    return flt.column if flt.bound and flt.column else flt.control


def _show_filters(preview):
    """List every filter the screen has, numbered, with what is in it now.

    All of them, never a sample. A filter missing from this list is one the
    operator cannot know to ask for, and the previous prompt showed none at
    all - so the only discoverable filters were the ones already remembered
    from a previous run."""
    settable = preview.settable
    print(f"\n  Filters on this screen ({len(settable)}):")
    for index, flt in enumerate(settable, start=1):
        label = flt.label or flt.column or flt.control
        current = f"  now: {flt.value!r}" if (flt.value or "").strip() else ""
        typed = "" if flt.bound else "  (typed - the screen fills this in code)"
        print(f"    {index:>3}. {label:<28} [{_filter_name(flt)}]{current}{typed}")
    return settable


def _show_options(preview):
    """List the left-panel options with the state the screen reports.

    These are not filters. Org/Prod/Fac/Proc and the Quick View entries
    REBUILD the panel when clicked, which invalidates every control found
    before them, and Plan Date versus Create Date silently changes which
    date the period means. Choosing one from a list is the only way to pick
    it deliberately."""
    print(f"\n  Left-panel options ({len(preview.options)}) - these change what the query means:")
    for index, option in enumerate(preview.options, start=1):
        print(f"    o{index:<2} {option.label:<28} [{option.state}]")
    if not preview.options:
        print("    (none found on this screen)")
    return preview.options


def _show_context(preview):
    divisions = preview.divisions
    if divisions:
        print(f"\n  Divisions that can be ticked ({len(divisions)}): {', '.join(divisions)}")
    if preview.date_columns:
        print(f"  Result date columns for verification: {', '.join(preview.date_columns)}")
    others = [quick for quick in preview.quick_views if not quick.active]
    if others:
        listed = ", ".join(f"{quick.screen} ({quick.name})" for quick in others)
        print(f"\n  Quick View leads to OTHER screens: {listed}")
        print("  Each is its own screen code, not an option here - run it as a separate report.")
    for warning in preview.warnings:
        print(f"  note: {warning}")


def _ask_filters(settable, saved):
    """Collect filter values by number or by name, one at a time."""
    chosen = dict(saved)
    if chosen:
        print(f"\n  Remembered filters: "
              + "; ".join(f"{key}={value}" for key, value in chosen.items()))
    while True:
        answer = _ask("\n  Filter number or name (blank when finished)")
        if not answer:
            return [f"{key}={value}" for key, value in chosen.items()]
        if answer.isdigit() and 1 <= int(answer) <= len(settable):
            name = _filter_name(settable[int(answer) - 1])
        else:
            name = answer
        value = _ask(f"    value for {name} (blank removes it)")
        if value:
            chosen[name] = value
        else:
            chosen.pop(name, None)


def _ask_options(options, saved):
    answer = _ask("\n  Option numbers or labels, comma separated", ",".join(saved))
    picked = []
    for item in (piece.strip() for piece in answer.split(",")):
        if not item:
            continue
        if item.lower().startswith("o") and item[1:].isdigit():
            item = item[1:]
        if item.isdigit() and 1 <= int(item) <= len(options):
            picked.append(options[int(item) - 1].label)
        else:
            picked.append(item)
    return picked


def _ask_verify(preview, saved):
    """A dated run must name the result column that proves the date."""
    verify = saved
    while not verify:
        if preview.date_columns:
            print(f"  Result date columns seen: {', '.join(preview.date_columns)}")
        verify = _ask("  Result date column to verify")
    return verify


class _Interview:
    """The guided workflow's questions and printing - no browser work at all.

    Every browser action is routed through the same application facade as
    ``gmes run``; this object is handed to the application, which opens the
    screen, reads it, and calls back here to ask what to do with it.
    """

    def __init__(self):
        self.completed = True

    def choose_screen(self):
        profiles = application.known_profiles()
        if profiles:
            print("\nRemembered screens:")
            for index, profile in enumerate(profiles[:9], start=1):
                values = _profile_values(profile)
                details = ", ".join(f"{key}={value}" for key, value in values.items()
                                    if key != "sets" and value)
                print(f"  {index}. {profile.get('screen', '')}  "
                      f"{profile.get('title', '')}  {details}")
        default = profiles[0].get("screen", "") if profiles else ""
        answer = _ask("Screen code or remembered number", default)
        if answer.isdigit() and profiles and 1 <= int(answer) <= len(profiles[:9]):
            selected = profiles[int(answer) - 1]
            return selected.get("screen", ""), selected
        if not answer.strip():
            print("A screen code is required.")
            return "", None
        return answer.strip().upper(), application.load_profile(answer)

    def choose_values(self, preview, profile):
        saved = _profile_values(profile)
        print(f"\n{'=' * 70}\n  {preview.code}  {preview.title}\n{'=' * 70}")
        relearn = False
        if profile:
            print("Replay: press Enter to reuse the proved settings, c to see this "
                  "screen's choices and change them,")
            print("        or r to forget what was learned and record this screen "
                  "again from scratch.")
            choice = _ask("Run choice", "run").casefold()
            relearn = choice.startswith("r") and not choice.startswith("run")
            if not (relearn or choice.startswith("c")):
                return {
                    "division": saved.get("division") or None,
                    "date_from": saved.get("from") or None,
                    "date_to": saved.get("to") or None,
                    "verify": saved.get("verify") or None,
                    "sets": [f"{key}={value}" for key, value in saved["sets"].items()],
                    "options": list(profile.get("options") or []),
                    "export": "both",
                }
            if relearn:
                # A screen whose shape has moved refuses to replay, and without
                # this the operator has nowhere to go but the command line.
                print("Recording this screen again. What was learned before is ignored.")
                saved = _profile_values(None)
        settable = _show_filters(preview)
        options = _show_options(preview)
        _show_context(preview)

        division = _ask("\n  Division (blank keeps none)", str(saved.get("division") or ""))
        date_from = _ask("  From date YYYYMMDD (blank means no date filter)",
                         str(saved.get("from") or ""))
        date_to = _ask("  To date YYYYMMDD (blank means no date filter)",
                       str(saved.get("to") or ""))
        verify = str(saved.get("verify") or "")
        if date_from or date_to:
            verify = _ask_verify(preview, verify)
        return {
            "division": division or None,
            "date_from": date_from or None,
            "date_to": date_to or None,
            "verify": verify or None,
            "sets": _ask_filters(settable, saved["sets"]),
            "options": _ask_options(options, [] if relearn
                                    else list((profile or {}).get("options") or [])),
            "export": "both",
            "relearn": relearn,
        }

    def report(self, result):
        if result.ok:
            names = ", ".join(os.path.basename(path) for path in result.files) \
                or "no file requested"
            print(f"COMPLETE: {result.screen}, {result.rows} rows, {names}")
        else:
            print(f"STOPPED: {result.error}")
            if "--relearn" in (result.error or ""):
                print("        Run this screen again and answer r at the Run choice "
                      "prompt to record it from scratch.")
            self.completed = False

    def report_open_failure(self, code, error):
        print(f"STOPPED: {code} could not be opened - {error}")
        self.completed = False

    def again(self):
        return not _ask("\nAnother report? y/n", "n").casefold().startswith("n")


def _workflow():
    """The compatibility-friendly guided entry point.

    It deliberately contains presentation and questions only.  One sign-in
    covers the whole sitting, so the screen the operator was shown is the
    screen that runs.
    """
    print("G-MES guided workflow. The same verified engine powers this and 'gmes run'.")
    interview = _Interview()
    try:
        execution = application.execute_guided_workflow(interview)
    except _WorkflowInputClosed:
        print("Workflow stopped because no more input was available.")
        return 1
    if not execution.ok:
        print(f"Sign-in did not complete: {execution.login.detail or 'no detail'}")
        return 1
    return 0 if execution.value and interview.completed else 1


def _run(args):
    execution = application.execute_run_request(
        args.screens, division=args.division, tree=args.tree, date_from=args.date_from,
        date_to=args.date_to, date=args.date, sets=args.set, options=args.option,
        grid=args.grid, verify=args.verify, export=args.export, out_dir=args.output_dir,
        dry_run=args.dry_run, close_after=args.close_tabs, use_profile=not args.no_profile,
        relearn=args.relearn)
    if execution.login.outcome.name != "OK":
        print("Sign-in did not complete. Nothing was run.")
        return 1
    return 0 if _render_run_summary(execution.results) == len(execution.results) else 1


def _render_run_summary(results):
    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    print(f"  {'SCREEN':<14} {'STATUS':<9} {'ROWS':>7}  FILES / ERROR")
    for result in results:
        detail = ", ".join(os.path.basename(path) for path in result.files) or "-" if result.ok else result.error
        status, rows = ("ok", str(result.rows)) if result.ok else ("FAILED", "-")
        print(f"  {result.screen:<14} {status:<9} {rows:>7}  {detail}")
    succeeded = sum(result.ok for result in results)
    print(f"\n  {succeeded}/{len(results)} succeeded")
    return succeeded


def _data(args):
    if args.data_command == "forms":
        execution = application.execute_data_forms()
        if not execution.ok:
            print("Sign-in did not complete. No forms were read.")
            return 1
        info = execution.value
        print(f"Open forms: {info.get('count', 0)}")
        for form in info.get("forms", []):
            print(f"  {form.get('file') or '(no file)'}: {', '.join(form.get('datasets', []))}")
        return 0
    execution = application.execute_data_read(args.screen_code, args.dataset,
                                               limit=args.limit, offset=args.offset)
    if not execution.ok:
        print("Sign-in did not complete. No dataset was read.")
        return 1
    result = execution.data
    if not result.get("found"):
        print(f"No dataset {args.dataset!r} on {args.screen_code!r}.")
        return 1
    print(f"Screen  : {result.get('file', '')}")
    print(f"Dataset : {args.dataset}   total rows: {result['total']}")
    hidden = ("token", "password", "credential", "secret", "authorization", "cookie")
    columns = [column for column in result["columns"]
               if not any(word in column.casefold() for word in hidden)]
    print(f"Columns : {', '.join(columns)}")
    for index, row in enumerate(result["rows"]):
        shown = {key: value for key, value in row.items()
                 if value and not key.startswith("_")
                 and not any(word in key.casefold() for word in hidden)}
        print(f"  [{index + args.offset}] {shown}")
    return 0


def main(argv=None):
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            parser.print_help()
            return 1
        if args.command == "version":
            print(application.package_version())
            return 0
        if args.command == "login":
            attempt = application.execute_login(assist=args.assist,
                                                refresh_profile=args.refresh_profile)
            return 0 if attempt.outcome.name == "OK" else 1
        if args.command == "migrate":
            message = application.migrate_credentials()
            print(message or "No legacy credentials needed migration.")
            return 0
        if args.command == "credentials":
            result = application.set_credentials()
            print(result.message)
            return 0 if result.saved else 1
        if args.command == "doctor":
            report = application.execute_doctor()
            print(report.render())
            return report.exit_code
        if args.command == "workflow":
            return _workflow()
        if args.command == "run":
            return _run(args)
        if args.command == "data":
            if args.data_command == "read" and (args.limit < -1 or args.offset < 0):
                raise ValueError("--limit must be -1 or a non-negative number, and --offset must be non-negative")
            return _data(args)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"gmes: error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
